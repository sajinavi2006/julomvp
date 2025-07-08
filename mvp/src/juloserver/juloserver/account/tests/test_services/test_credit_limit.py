import json
from datetime import datetime, timedelta
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.test import TestCase
from mock import patch

from juloserver.account.constants import CreditMatrixType, AccountConstant
from juloserver.account.models import Account, AccountLimit, CreditLimitGeneration
from juloserver.account.services.credit_limit import (
    calculate_credit_limit,
    generate_credit_limit,
    get_change_limit_amount,
    get_credit_matrix_parameters_from_account_property,
    get_credit_matrix_type,
    store_credit_limit_generated,
    store_related_data_for_generate_credit_limit,
    update_available_limit,
    update_credit_limit_with_clcs,
    is_using_turbo_limit,
    update_account_max_limit_pre_matrix_with_cfs,
    get_triple_pgood_limit,
    get_non_fdc_job_check_fail_limit,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
    AccountPropertyFactory,
    CreditLimitGenerationFactory,
)
from juloserver.account.utils import round_down_nearest
from juloserver.ana_api.tests.factories import EligibleCheckFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.cfs.tests.factories import PdClcsPrimeResultFactory
from juloserver.early_limit_release.constants import ReleaseTrackingType
from juloserver.entry_limit.constants import CreditLimitGenerationReason
from juloserver.julo.constants import FeatureNameConst, WorkflowConst, ExperimentConst
from juloserver.julo.models import ApplicationNote, FeatureSetting, StatusLookup, Loan
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    AffordabilityHistoryFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    AuthUserFactory,
    BankStatementSubmitFactory,
    BankStatementSubmitBalanceFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    CustomerFactory,
    ExperimentSettingFactory,
    FeatureSettingFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.early_limit_release.tests.factories import ReleaseTrackingFactory
from juloserver.rentee.services import RENTEE_RESIDUAL_PERCENTAGE
from juloserver.rentee.tests.factories import PaymentDepositFactory
from juloserver.julocore.cache_client import get_loc_mem_cache
from juloserver.utilities.services import HoldoutManager
from juloserver.application_flow.factories import ApplicationPathTagStatusFactory
from juloserver.new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.julo.services2.redis_helper import MockRedisHelper


class TestCreditLimit(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account_lookup = AccountLookupFactory()
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')

        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.shopee_whitelist_fs = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SHOPEE_WHITELIST_SCORING,
            description="",
            parameters={
                'good_fdc_bypass': {"is_active": True},
                'submitted_bank_statement_bypass': {"is_active": True},
            },
        )
        self.lbs_bypass_es = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.LBS_130_BYPASS,
            criteria={
                'limit_total_of_application_min_affordability': 700,
                'limit_total_of_application_swap_out_dukcapil': 700,
            },
        )
        self.lbs_bypass_es = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.LANNISTER_EXPERIMENT,
            action='{"count": 0}',
            criteria={
                'limit': 1500,
                'experiment_group': "1,2,3",
                "cm_parameter": "feature:is_goldfish",
            },
        )
        self.fake_redis = MockRedisHelper()

    def test_store_related_data_for_generate_credit_limit(self):
        self.application.workflow = self.account_lookup.workflow
        self.application.save()
        self.application.refresh_from_db()
        store_related_data_for_generate_credit_limit(self.application, 600000, 550000)
        self.assertIsNotNone(Account.objects.last())
        self.assertIsNotNone(AccountLimit.objects.last())

    def test_store_credit_limit_generated(self):
        self.application.workflow = self.account_lookup.workflow
        self.application.save()
        self.application.refresh_from_db()

        reason = "130 Credit Limit Generation"
        store_credit_limit_generated(
            self.application,
            None,
            self.credit_matrix,
            self.affordability_history,
            6000000,
            4500000,
            json.dumps(
                {'simple_limit': 3030303, 'reduced_limit': 2424242, 'limit_adjustment_factor': 0.8}
            ),
            reason,
        )
        self.assertIsNotNone(CreditLimitGeneration.objects.last())

    def test_calculate_credit_limit(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_rounding_down_value',
            description="Rounding down minimum value for credit limit",
            parameters={'rounding_down_value': 300000},
        )
        credit_limit_result = calculate_credit_limit(self.credit_matrix_product_line, 560000, 1)
        assert credit_limit_result['max_limit'] > 0

    def test_calculate_credit_limit_below_500k(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_rounding_down_value',
            description="Rounding down minimum value for credit limit",
            parameters={'rounding_down_value': 300000},
        )
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            interest=0.09, min_loan_amount=500000, max_loan_amount=500000, max_duration=2
        )
        credit_limit_result = calculate_credit_limit(credit_matrix_product_line, 306029, 0.8)
        assert credit_limit_result['set_limit'] == 300000

    def test_calculate_credit_limit_below_300k(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_rounding_down_value',
            description="Rounding down minimum value for credit limit",
            parameters={'rounding_down_value': 300000},
        )
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            interest=0.08, min_loan_amount=150000, max_loan_amount=150000, max_duration=2
        )
        credit_limit_result = calculate_credit_limit(credit_matrix_product_line, 900000, 0.8)
        assert credit_limit_result['set_limit'] < 300000

    def test_calculate_credit_limit_equal_300k_without_feature_rounding(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_rounding_down_value',
            description="Rounding down minimum value for credit limit",
            parameters={'rounding_down_value': 300000},
        )
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            interest=0.09, min_loan_amount=300000, max_loan_amount=300000, max_duration=2
        )
        credit_limit_result = calculate_credit_limit(credit_matrix_product_line, 1280204, 0.8)
        assert credit_limit_result['set_limit'] == 300000

    def test_calculate_credit_limit_equal_500k(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_rounding_down_value',
            description="Rounding down minimum value for credit limit",
            parameters={'rounding_down_value': 300000},
        )
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            interest=0.09, min_loan_amount=500000, max_loan_amount=500000, max_duration=2
        )
        credit_limit_result = calculate_credit_limit(credit_matrix_product_line, 1571311, 0.8)
        assert credit_limit_result['set_limit'] == 500000

    def test_calculate_credit_limit_above_500k(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_rounding_down_value',
            description="Rounding down minimum value for credit limit",
            parameters={'rounding_down_value': 300000},
        )
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            interest=0.09, min_loan_amount=500000, max_loan_amount=1000000, max_duration=5
        )
        credit_limit_result = calculate_credit_limit(credit_matrix_product_line, 1000660, 0.9)
        assert credit_limit_result['set_limit'] == 1000000

    def test_round_down_nearest(self):
        test_cases_lte_5000000 = [(4999122, 4500000), (4500023, 4500000), (4122121, 4000000)]
        for number, expected_number in test_cases_lte_5000000:
            assert round_down_nearest(number, 500000) == expected_number

        test_cases_number_gt_5000000 = [(9944172, 9000000), (6988741, 6000000), (6200121, 6000000)]
        for number, expected_number in test_cases_number_gt_5000000:
            assert round_down_nearest(number, 1000000) == expected_number

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    @patch('juloserver.account.services.credit_limit.get_credit_model_result')
    @patch('juloserver.account.services.credit_limit.check_positive_processed_income')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.account.services.credit_limit.store_credit_limit_generated')
    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix')
    @patch('juloserver.account.services.credit_limit.get_transaction_type')
    @patch('juloserver.account.services.credit_limit.compute_affordable_payment')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_generate_credit_limit(
        self,
        mock_get_credit_matrix_parameters,
        mock_compute_affordable_payment,
        mock_get_transaction_type,
        mock_get_credit_matrix,
        mock_calculate_credit_limit,
        mock_store_credit_limit_generated,
        mock_process_application_status_change,
        mock_check_positive_processed_income,
        mocked_credit_model,
        mock_cache,
        mock_get_client,
    ):
        mock_compute_affordable_payment.return_value = 600000
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.79
        )
        mocked_credit_model.return_value = pd_credit_model_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        mock_get_client.return_value = self.fake_redis
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_calculate_credit_limit.assert_called_once_with(
            self.credit_matrix_product_line, self.affordability_history.affordability_value, 1
        )
        mock_store_credit_limit_generated.assert_called_once()
        mocked_credit_model.assert_called()
        assert max_limit >= 0

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    @patch('juloserver.account.services.credit_limit.get_credit_model_result')
    @patch('juloserver.account.services.credit_limit.check_positive_processed_income')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.account.services.credit_limit.store_credit_limit_generated')
    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix')
    @patch('juloserver.account.services.credit_limit.get_transaction_type')
    @patch('juloserver.account.services.credit_limit.compute_affordable_payment')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_generate_credit_limit_with_available_sonic_passed(
        self,
        mock_get_credit_matrix_parameters,
        mock_compute_affordable_payment,
        mock_get_transaction_type,
        mock_get_credit_matrix,
        mock_calculate_credit_limit,
        mock_store_credit_limit_generated,
        mock_process_application_status_change,
        mock_check_positive_processed_income,
        mocked_credit_model,
        mock_cache,
        mock_get_client,
    ):
        # negative sonic affordability
        ApplicationNote.objects.create(
            application_id=self.application.id,
            note_text='change monthly income by bank scrape model',
        )
        ApplicationHistoryFactory(
            application_id=self.application.id, change_reason='SonicAffordability'
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name='credit_limit_reject_affordability_value',
            description="Configuration for limit credit generation",
            parameters={'limit_value_lf': 300000, "limit_value_sf": 400000},
        )
        mock_check_positive_processed_income.return_value = False
        self.affordability_history.affordability_value = 200000
        self.affordability_history.change_reason = 'SonicAffordability'
        self.affordability_history.save()
        pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.79
        )
        mocked_credit_model.return_value = pd_credit_model_score
        mock_get_client.return_value = self.fake_redis
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_process_application_status_change.assert_called_once()
        assert max_limit == 0
        assert set_limit == 0

        # positive affordability
        mock_compute_affordable_payment.return_value = {'affordable_payment': 600000}
        self.affordability_history.affordability_value = 600000
        self.affordability_history.save()
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        mock_get_credit_matrix.return_value = self.credit_matrix
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_calculate_credit_limit.assert_called_once_with(
            self.credit_matrix_product_line, 600000, 1
        )
        mock_store_credit_limit_generated.assert_called_once()
        mocked_credit_model.assert_called()
        assert max_limit >= 0

        # negative affordability
        mock_compute_affordable_payment.return_value = {'affordable_payment': 200000}
        self.affordability_history.affordability_value = 600000
        self.affordability_history.save()
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        mock_get_credit_matrix.return_value = self.credit_matrix
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_store_credit_limit_generated.assert_called_once()
        assert max_limit == 0

        # check positive processed income failed
        mock_check_positive_processed_income.return_value = False
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        mock_get_credit_matrix.return_value = self.credit_matrix
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        max_limit, set_limit = generate_credit_limit(self.application)
        assert max_limit >= 0

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    @patch('juloserver.account.services.credit_limit.get_credit_model_result')
    @patch('juloserver.account.services.credit_limit.check_positive_processed_income')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.account.services.credit_limit.store_credit_limit_generated')
    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix')
    @patch('juloserver.account.services.credit_limit.get_transaction_type')
    @patch('juloserver.account.services.credit_limit.compute_affordable_payment')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_generate_credit_limit_lbs_higher_eom_pass_threshold(
        self,
        mock_get_credit_matrix_parameters,
        mock_compute_affordable_payment,
        mock_get_transaction_type,
        mock_get_credit_matrix,
        mock_calculate_credit_limit,
        mock_store_credit_limit_generated,
        mock_process_application_status_change,
        mock_check_positive_processed_income,
        mocked_credit_model,
        mock_cache,
        mock_get_client,
    ):
        mock_compute_affordable_payment.return_value = 600000
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.79
        )
        mocked_credit_model.return_value = pd_credit_model_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        ExperimentSettingFactory(
            code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT,
            criteria={
                "credit_limit_constant": 1.5,
                "credit_limit_threshold": 150000,
                "max_limit": 5000000,
                "a/b_test": {"per_request": 2, "percentage": 50},
            },
            is_active=True,
        )
        tag = 'is_submitted_bank_statement'
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )
        bank_statement_submit = BankStatementSubmitFactory(application_id=self.application.id)
        current_time = timezone.now()

        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=3),
            minimum_eod_balance=100000,
            average_eod_balance=100000,
            eom_balance=150000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=2),
            minimum_eod_balance=100000,
            average_eod_balance=100000,
            eom_balance=200000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=1),
            minimum_eod_balance=100000,
            average_eod_balance=100000,
            eom_balance=250000,
        )
        mock_get_client.return_value = self.fake_redis
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_calculate_credit_limit.assert_called_once_with(
            self.credit_matrix_product_line, self.affordability_history.affordability_value, 1
        )
        mock_store_credit_limit_generated.assert_called_once()
        mocked_credit_model.assert_called()
        assert max_limit == 5000000
        assert set_limit == 300000

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    @patch('juloserver.account.services.credit_limit.get_credit_model_result')
    @patch('juloserver.account.services.credit_limit.check_positive_processed_income')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.account.services.credit_limit.store_credit_limit_generated')
    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix')
    @patch('juloserver.account.services.credit_limit.get_transaction_type')
    @patch('juloserver.account.services.credit_limit.compute_affordable_payment')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_generate_credit_limit_lbs_higher_average_eod_pass_threshold(
        self,
        mock_get_credit_matrix_parameters,
        mock_compute_affordable_payment,
        mock_get_transaction_type,
        mock_get_credit_matrix,
        mock_calculate_credit_limit,
        mock_store_credit_limit_generated,
        mock_process_application_status_change,
        mock_check_positive_processed_income,
        mocked_credit_model,
        mock_cache,
        mock_get_client,
    ):
        mock_compute_affordable_payment.return_value = 600000
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.79
        )
        mocked_credit_model.return_value = pd_credit_model_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        ExperimentSettingFactory(
            code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT,
            criteria={
                "credit_limit_constant": 1.5,
                "credit_limit_threshold": 150000,
                "max_limit": 5000000,
                "a/b_test": {"per_request": 2, "percentage": 50},
            },
            is_active=True,
        )
        tag = 'is_submitted_bank_statement'
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )
        bank_statement_submit = BankStatementSubmitFactory(application_id=self.application.id)
        current_time = timezone.now()

        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=3),
            minimum_eod_balance=100000,
            average_eod_balance=200000,
            eom_balance=200000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=2),
            minimum_eod_balance=100000,
            average_eod_balance=300000,
            eom_balance=200000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=1),
            minimum_eod_balance=100000,
            average_eod_balance=400000,
            eom_balance=200000,
        )
        mock_get_client.return_value = self.fake_redis
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_calculate_credit_limit.assert_called_once_with(
            self.credit_matrix_product_line, self.affordability_history.affordability_value, 1
        )
        mock_store_credit_limit_generated.assert_called_once()
        mocked_credit_model.assert_called()
        assert max_limit == 5000000
        assert set_limit == 450000

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    @patch('juloserver.account.services.credit_limit.get_credit_model_result')
    @patch('juloserver.account.services.credit_limit.check_positive_processed_income')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.account.services.credit_limit.store_credit_limit_generated')
    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix')
    @patch('juloserver.account.services.credit_limit.get_transaction_type')
    @patch('juloserver.account.services.credit_limit.compute_affordable_payment')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_generate_credit_limit_lbs_pass_max_limit(
        self,
        mock_get_credit_matrix_parameters,
        mock_compute_affordable_payment,
        mock_get_transaction_type,
        mock_get_credit_matrix,
        mock_calculate_credit_limit,
        mock_store_credit_limit_generated,
        mock_process_application_status_change,
        mock_check_positive_processed_income,
        mocked_credit_model,
        mock_cache,
        mock_get_client,
    ):
        mock_compute_affordable_payment.return_value = 600000
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.79
        )
        mocked_credit_model.return_value = pd_credit_model_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        ExperimentSettingFactory(
            code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT,
            criteria={
                "credit_limit_constant": 1.5,
                "credit_limit_threshold": 150000,
                "max_limit": 5000000,
                "a/b_test": {"per_request": 2, "percentage": 50},
            },
            is_active=True,
        )
        tag = 'is_submitted_bank_statement'
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )
        bank_statement_submit = BankStatementSubmitFactory(application_id=self.application.id)
        current_time = timezone.now()
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=3),
            minimum_eod_balance=100000,
            average_eod_balance=5000000,
            eom_balance=200000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=2),
            minimum_eod_balance=100000,
            average_eod_balance=5000000,
            eom_balance=200000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=1),
            minimum_eod_balance=100000,
            average_eod_balance=5000000,
            eom_balance=200000,
        )
        mock_get_client.return_value = self.fake_redis
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_calculate_credit_limit.assert_called_once_with(
            self.credit_matrix_product_line, self.affordability_history.affordability_value, 1
        )
        mock_store_credit_limit_generated.assert_called_once()
        mocked_credit_model.assert_called()
        assert max_limit == 5000000
        assert set_limit == 5000000

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    @patch('juloserver.account.services.credit_limit.get_credit_model_result')
    @patch('juloserver.account.services.credit_limit.check_positive_processed_income')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.account.services.credit_limit.store_credit_limit_generated')
    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix')
    @patch('juloserver.account.services.credit_limit.get_transaction_type')
    @patch('juloserver.account.services.credit_limit.compute_affordable_payment')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_generate_credit_limit_lbs_under_threshold(
        self,
        mock_get_credit_matrix_parameters,
        mock_compute_affordable_payment,
        mock_get_transaction_type,
        mock_get_credit_matrix,
        mock_calculate_credit_limit,
        mock_store_credit_limit_generated,
        mock_process_application_status_change,
        mock_check_positive_processed_income,
        mocked_credit_model,
        mock_cache,
        mock_get_client,
    ):
        mock_compute_affordable_payment.return_value = 600000
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        mock_get_credit_matrix_parameters.return_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.79
        )
        mocked_credit_model.return_value = pd_credit_model_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        mock_check_positive_processed_income.return_value = True
        ExperimentSettingFactory(
            code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT,
            criteria={
                "credit_limit_constant": 1.5,
                "credit_limit_threshold": 150000,
                "max_limit": 5000000,
                "a/b_test": {"per_request": 2, "percentage": 50},
            },
            is_active=True,
        )
        tag = 'is_submitted_bank_statement'
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )
        bank_statement_submit = BankStatementSubmitFactory(application_id=self.application.id)
        current_time = timezone.now()
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=3),
            minimum_eod_balance=10000,
            average_eod_balance=80000,
            eom_balance=80000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=2),
            minimum_eod_balance=10000,
            average_eod_balance=80000,
            eom_balance=80000,
        )
        BankStatementSubmitBalanceFactory(
            bank_statement_submit=bank_statement_submit,
            balance_date=current_time - relativedelta(months=1),
            minimum_eod_balance=10000,
            average_eod_balance=80000,
            eom_balance=80000,
        )
        mock_get_client.return_value = self.fake_redis
        max_limit, set_limit = generate_credit_limit(self.application)
        mock_calculate_credit_limit.assert_called_once_with(
            self.credit_matrix_product_line, self.affordability_history.affordability_value, 1
        )
        mocked_credit_model.assert_called()
        assert max_limit is 0
        assert set_limit is 0

    def test_get_credit_matrix_parameters_from_account_property(self):
        account = AccountFactory(customer=self.application.customer)
        account.save()
        account_property = AccountPropertyFactory(account=account)
        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        self.assertIsNotNone(credti_matrix)

    def test_get_credit_matrix_type(self):
        julo1_repeat = get_credit_matrix_type(self.application, is_proven=True)
        self.assertEqual(julo1_repeat, CreditMatrixType.JULO1_PROVEN)

        julo1 = get_credit_matrix_type(self.application, is_proven=False)
        self.assertEqual(julo1, CreditMatrixType.JULO1)
        # test MTL already upgraded to J1 => return J1
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.MTL1)
        application = ApplicationFactory(customer=self.customer, product_line=product_line)
        paid_off_status = StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF)
        LoanFactory(application=application, customer=self.customer, loan_status=paid_off_status)
        loan_mtl_count = (
            Loan.objects.get_queryset()
            .paid_off()
            .filter(
                customer=application.customer,
                application__product_line__product_line_code__in=ProductLineCodes.mtl(),
            )
            .count()
        )
        assert loan_mtl_count == 1
        julo1 = get_credit_matrix_type(self.application, is_proven=False)
        self.assertEqual(julo1, CreditMatrixType.JULO1)

    def test_get_credit_matrix_parameters_from_account_property_with_good_fdc(self):
        # 1. Not good FDC
        pgood = 0.5
        account = AccountFactory(customer=self.application.customer)
        account_property = AccountPropertyFactory(account=account, pgood=pgood)
        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == pgood
        assert credti_matrix['max_threshold__gte'] == pgood

        # 2. Good FDC
        pgood = AccountConstant.PGOOD_BYPASS_CREDIT_MATRIX
        tag = 'is_good_fdc_el'
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )
        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == pgood
        assert credti_matrix['max_threshold__gte'] == pgood

        # 3. fs is off
        self.shopee_whitelist_fs.parameters['good_fdc_bypass'].update(dict(is_active=False))
        self.shopee_whitelist_fs.save()

        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == account_property.pgood
        assert credti_matrix['max_threshold__gte'] == account_property.pgood

        # 4. not exists in parameters
        self.shopee_whitelist_fs.parameters = {}
        self.shopee_whitelist_fs.save()

        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == account_property.pgood
        assert credti_matrix['max_threshold__gte'] == account_property.pgood

    def test_get_credit_matrix_parameters_from_account_property_with_submitted_bank_statement(self):
        # 1. Not good FDC
        pgood = 0.5
        account = AccountFactory(customer=self.application.customer)
        account_property = AccountPropertyFactory(account=account, pgood=pgood)
        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == pgood
        assert credti_matrix['max_threshold__gte'] == pgood

        # 2. Good FDC
        pgood = AccountConstant.PGOOD_BYPASS_CREDIT_MATRIX
        tag = 'is_submitted_bank_statement'
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )
        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == pgood
        assert credti_matrix['max_threshold__gte'] == pgood

        # 3. fs is off
        self.shopee_whitelist_fs.parameters['good_fdc_bypass'].update(dict(is_active=False))
        self.shopee_whitelist_fs.save()

        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == account_property.pgood
        assert credti_matrix['max_threshold__gte'] == account_property.pgood

        # 4. not exists in parameters
        self.shopee_whitelist_fs.parameters = {}
        self.shopee_whitelist_fs.save()

        credti_matrix = get_credit_matrix_parameters_from_account_property(
            self.application, account_property
        )
        assert credti_matrix['min_threshold__lte'] == account_property.pgood
        assert credti_matrix['max_threshold__gte'] == account_property.pgood


class TestCreditLimitLoanRelated(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.application = ApplicationFactory(account=self.account)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.loan = LoanFactory(loan_amount=50000, account=self.account_limit.account)

    def test_decrease_available_limit(self):
        loan = self.loan
        previous_limit = self.account_limit.available_limit
        inactive_loan_status = StatusLookup.objects.get(pk=LoanStatusCodes.INACTIVE)
        loan.loan_status = inactive_loan_status
        loan.save()
        with transaction.atomic():
            update_available_limit(loan)
        account_limit = AccountLimit.objects.get(account=loan.account)
        self.assertGreater(previous_limit, account_limit.available_limit)

    def test_increase_available_limit(self):
        loan = self.loan
        previous_limit = self.account_limit.available_limit
        inactive_loan_status = StatusLookup.objects.get(pk=LoanStatusCodes.PAID_OFF)
        loan.loan_status = inactive_loan_status
        loan.save()
        with transaction.atomic():
            update_available_limit(loan)
        account_limit = AccountLimit.objects.get(account=loan.account)
        self.assertGreater(account_limit.available_limit, previous_limit)

    def test_available_limit_not_change(self):
        loan = self.loan
        previous_limit = self.account_limit.available_limit
        inactive_loan_status = StatusLookup.objects.get(pk=LoanStatusCodes.LOAN_1DPD)
        loan.loan_status = inactive_loan_status
        loan.save()
        with transaction.atomic():
            update_available_limit(loan)
        account_limit = AccountLimit.objects.get(account=loan.account)
        self.assertEqual(account_limit.available_limit, previous_limit)

    def test_success_get_change_limit_amount_rentee_loan(self):
        PaymentDepositFactory(loan=self.loan)
        change_limit_amount = get_change_limit_amount(self.loan)
        loan_value = self.loan.loan_amount * RENTEE_RESIDUAL_PERCENTAGE
        self.assertEqual(change_limit_amount, loan_value)

    def test_revert_limit_for_early_limit_release(self):
        paid_off_status = StatusLookup.objects.get(pk=LoanStatusCodes.PAID_OFF)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        loan_amount = 500000
        limit_release_amount = 200000

        loan = self.loan
        application = ApplicationFactory(product_line=product_line, account=loan.account)
        loan.loan_amount = loan_amount
        loan.loan_status = paid_off_status
        loan.application = application
        loan.save()

        # suppose user uses all available_limit with 500000
        self.account_limit.available_limit = 0
        self.account_limit.used_limit = loan_amount

        # the user have early limit release
        self.account_limit.available_limit += limit_release_amount
        self.account_limit.used_limit -= limit_release_amount
        self.account_limit.save()

        ReleaseTrackingFactory(
            limit_release_amount=limit_release_amount,
            account=loan.account,
            loan=loan,
            payment=loan.payment_set.first(),
            type=ReleaseTrackingType.EARLY_RELEASE,
        )

        with transaction.atomic():
            update_available_limit(loan)
        account_limit = AccountLimit.objects.get(account=loan.account)
        self.assertEqual(account_limit.available_limit, loan.loan_amount)

    @patch('juloserver.early_limit_release.services.get_julo_sentry_client')
    def test_revert_limit_for_early_limit_release_negative(self, _mock_get_julo_sentry_client):
        # expected: if the limit_release_amount > loan.loan_amount, not update
        paid_off_status = StatusLookup.objects.get(pk=LoanStatusCodes.PAID_OFF)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        loan_amount = 500000
        limit_release_amount = 20000000

        loan = self.loan
        application = ApplicationFactory(product_line=product_line, account=loan.account)
        loan.loan_amount = loan_amount
        loan.loan_status = paid_off_status
        loan.application = application
        loan.save()

        # suppose user uses all available_limit with 500000
        self.account_limit.available_limit = 0
        self.account_limit.used_limit = loan_amount

        # the user have early limit release
        self.account_limit.available_limit += limit_release_amount
        self.account_limit.used_limit -= limit_release_amount
        self.account_limit.save()
        previous_limit = self.account_limit.available_limit

        ReleaseTrackingFactory(
            limit_release_amount=limit_release_amount,
            account=loan.account,
            loan=loan,
            payment=loan.payment_set.first(),
            type=ReleaseTrackingType.EARLY_RELEASE,
        )

        with transaction.atomic():
            update_available_limit(loan)
        account_limit = AccountLimit.objects.get(account=loan.account)
        self.assertEqual(account_limit.available_limit, previous_limit)


class TestCreditLimitClcsRelated(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(
            account=self.account,
            is_entry_level=False,
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application.save()
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=3000, set_limit=2000, used_limit=0, available_limit=1500
        )
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        CreditLimitGenerationFactory(
            account=self.account, application=self.application, max_limit=50000, set_limit=50000
        )
        self.today = datetime.now().date()
        self.mock_credit_limit_calculation = {
            'simple_limit': 600000,
            'reduced_limit': 510000,
            'simple_limit_rounded': 500000,
            'reduced_limit_rounded': 500000,
            'max_limit': 600000,
            'set_limit': 600000,
            'limit_adjustment_factor': 0.80,
        }
        self.mock_get_matrix_params_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.CFS,
            parameters={'is_active_limit_recalculation': True},
            is_active=True,
        )

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_recalculation_with_clcs(self, mock_get_matrix, mock_calculate_credit_limit):
        mock_get_matrix.return_value = (self.credit_matrix, self.credit_matrix_product_line)
        mock_calculate_credit_limit.return_value = self.mock_credit_limit_calculation

        two_days = timedelta(days=2)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            clcs_prime_score=0.94,
            partition_date=self.today + two_days,
        )

        update_credit_limit_with_clcs(self.application)
        self.account_limit.refresh_from_db()

        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=self.application, reason=CreditLimitGenerationReason.RECALCULATION_WITH_CLCS
        ).last()
        self.assertIsNotNone(last_credit_generation)
        self.assertEqual(
            self.account_limit.available_limit,
            self.mock_credit_limit_calculation['set_limit'] - self.account_limit.used_limit,
        )

    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_recalculation_with_clcs_case_no_score(self, mock_get_matrix):
        two_days = timedelta(days=2)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            clcs_prime_score=0.94,
            partition_date=self.today - two_days,
        )
        update_credit_limit_with_clcs(self.application)
        self.account_limit.refresh_from_db()
        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=self.application, reason=CreditLimitGenerationReason.RECALCULATION_WITH_CLCS
        ).last()
        self.assertIsNone(last_credit_generation)
        mock_get_matrix.assert_not_called()

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    def test_recalculation_with_clcs_case_used_limit_zero(
        self, mock_get_matrix, mock_calculate_credit_limit
    ):
        mock_get_matrix.return_value = (self.credit_matrix, self.credit_matrix_product_line)
        mock_calculate_credit_limit.return_value = self.mock_credit_limit_calculation
        self.account_limit.used_limit = 5000
        self.account_limit.save()
        two_days = timedelta(days=2)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            clcs_prime_score=0.94,
            partition_date=self.today + two_days,
        )

        update_credit_limit_with_clcs(self.application)
        self.account_limit.refresh_from_db()
        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=self.application, reason=CreditLimitGenerationReason.RECALCULATION_WITH_CLCS
        ).last()
        self.assertIsNone(last_credit_generation)

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_recalculation_with_clcs_case_nochange(
        self, mock_get_matrix, mock_calculate_credit_limit
    ):
        mock_get_matrix.return_value = (self.credit_matrix, self.credit_matrix_product_line)
        mock_calculate_credit_limit.return_value = self.mock_credit_limit_calculation

        two_days = timedelta(days=2)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            clcs_prime_score=0.94,
            partition_date=self.today + two_days,
        )

        self.account_limit.set_limit = self.mock_credit_limit_calculation['set_limit']
        self.account_limit.save()
        old_limit, new_limit = update_credit_limit_with_clcs(self.application)
        self.assertEqual(old_limit, new_limit)

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_recalculation_with_clcs_case_increase(
        self, mock_get_matrix, mock_calculate_credit_limit
    ):
        mock_get_matrix.return_value = (self.credit_matrix, self.credit_matrix_product_line)
        mock_calculate_credit_limit.return_value = self.mock_credit_limit_calculation

        two_days = timedelta(days=2)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            clcs_prime_score=0.94,
            partition_date=self.today + two_days,
        )

        self.account_limit.set_limit = self.mock_credit_limit_calculation['set_limit'] - 100
        self.account_limit.save()
        old_limit, new_limit = update_credit_limit_with_clcs(self.application)
        self.account_limit.refresh_from_db()
        self.assertGreater(new_limit, old_limit)
        self.assertEqual(new_limit, self.account_limit.set_limit)

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_recalculation_with_clcs_case_decrease(
        self, mock_get_matrix, mock_calculate_credit_limit
    ):
        mock_get_matrix.return_value = (self.credit_matrix, self.credit_matrix_product_line)
        mock_calculate_credit_limit.return_value = self.mock_credit_limit_calculation

        two_days = timedelta(days=2)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            clcs_prime_score=0.94,
            partition_date=self.today + two_days,
        )

        self.account_limit.set_limit = self.mock_credit_limit_calculation['set_limit'] + 100
        self.account_limit.save()
        old_limit, new_limit = update_credit_limit_with_clcs(self.application)
        self.account_limit.refresh_from_db()
        self.assertGreater(old_limit, new_limit)
        self.assertEqual(new_limit, self.account_limit.set_limit)

    def test_recalculation_case_not_feature_setting(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        result = update_credit_limit_with_clcs(self.application)
        self.assertIsNone(result)

    def test_recalculation_case_not_active(self):
        self.feature_setting.parameters['is_active_limit_recalculation'] = False
        self.feature_setting.save()
        result = update_credit_limit_with_clcs(self.application)
        self.assertIsNone(result)

    def test_recalculation_case_entry_level(self):
        self.account_property.is_entry_level = True
        self.account_property.save()
        result = update_credit_limit_with_clcs(self.application)
        self.assertIsNone(result)

    def test_recalculation_case_partner(self):
        self.application.partner = PartnerFactory()
        self.application.save()
        result = update_credit_limit_with_clcs(self.application)
        self.assertIsNone(result)

    def test_is_turbo_limit_have_increase_or_not(self):

        data_limit = {'max_limit': 15000000, 'set_limit': 15000000}
        expected_result = True

        # set application J1 in x190
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        # create application jturbo
        self.application_jturbo = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            product_line=ProductLineFactory(product_line_code=2),
        )

        # create credit limit
        credit_limit_for_j1 = CreditLimitGenerationFactory(
            account=self.account, application=self.application, **data_limit
        )
        credit_limit_for_jturbo = CreditLimitGenerationFactory(
            account=self.account, application=self.application_jturbo, **data_limit
        )

        self.application_jturbo.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
            )
        )

        # check case if user not increase limit
        result = is_using_turbo_limit(self.application)
        self.assertEqual(result, expected_result)

        data_limit = {'max_limit': 10000000, 'set_limit': 10000000}

        credit_limit_for_j1.update_safely(**data_limit)
        # check case if user not increase limit
        # J1 limit got limit lower from JTurbo
        result = is_using_turbo_limit(self.application)
        self.assertEqual(result, expected_result)

        data_limit = {'max_limit': 500000, 'set_limit': 500000}
        expected_result = False
        credit_limit_for_jturbo.update_safely(**data_limit)
        # check case if user have increase limit
        # J1 limit got limit upper from JTurbo
        result = is_using_turbo_limit(self.application)
        self.assertEqual(result, expected_result)


class TestCreditLimitCFSRelated(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(
            account=self.account,
            is_entry_level=False,
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application.save()
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.mock_get_matrix_params_value = dict(
            min_threshold__lte=self.credit_matrix.min_threshold,
            max_threshold__gte=self.credit_matrix.min_threshold,
            credit_matrix_type='julo1',
            is_salaried=True,
            is_premium_area=True,
        )

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    def test_recalculation_with_cfs_update_account_limit(self, mock_calculate_credit_limit):
        # New max_limit > current max_limit
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 3000000,
            'reduced_limit': 2000000,
            'simple_limit_rounded': 3000000,
            'reduced_limit_rounded': 2000000,
            'max_limit': 4000000,
            'set_limit': 3000000,
            'limit_adjustment_factor': 0.8,
        }

        CreditLimitGenerationFactory(
            account=self.account, application=self.application,
            max_limit=1000000, set_limit=1000000,
            credit_matrix=self.credit_matrix,
            log=json.dumps({
                "simple_limit": 6000000,
                "reduced_limit": 6000000,
                "limit_adjustment_factor": 0.9,
                "max_limit (pre-matrix)": 2400000,
                "set_limit (pre-matrix)": 2400000
            })
        )

        update_account_max_limit_pre_matrix_with_cfs(self.application, self.affordability_history)

        # Credit limit generation created
        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=self.application, reason=CreditLimitGenerationReason.UPDATE_MONTHLY_INCOME
        ).last()
        self.assertIsNotNone(last_credit_generation)

        self.assertEqual(last_credit_generation.max_limit, 1000000)
        self.assertEqual(last_credit_generation.set_limit, 1000000)
        credit_limit_generation_log = json.loads(last_credit_generation.log)
        self.assertEqual(credit_limit_generation_log['max_limit (pre-matrix)'], 3000000)
        self.assertEqual(credit_limit_generation_log['set_limit (pre-matrix)'], 2000000)

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    def test_recalculation_with_cfs_no_update_account_limit(self, mock_calculate_credit_limit):
        # New max_limit < current max_limit
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 1000000,
            'reduced_limit': 500000,
            'simple_limit_rounded': 1000000,
            'reduced_limit_rounded': 500000,
            'max_limit': 1800000,
            'set_limit': 1500000,
            'limit_adjustment_factor': 0.8,
        }

        CreditLimitGenerationFactory(
            account=self.account, application=self.application,
            max_limit=1000000, set_limit=1000000,
            credit_matrix=self.credit_matrix,
            log=json.dumps({
                "simple_limit": 6000000,
                "reduced_limit": 6000000,
                "limit_adjustment_factor": 0.9,
                "max_limit (pre-matrix)": 2400000,
                "set_limit (pre-matrix)": 2400000
            })
        )

        update_account_max_limit_pre_matrix_with_cfs(self.application, self.affordability_history)

        # Credit limit generation not created
        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=self.application, reason=CreditLimitGenerationReason.UPDATE_MONTHLY_INCOME
        ).last()
        self.assertIsNone(last_credit_generation)

    @patch('juloserver.account.services.credit_limit.calculate_credit_limit')
    def test_recalculation_with_cfs_no_limit_adjustment_factor(self, mock_calculate_credit_limit):
        mock_calculate_credit_limit.return_value = {
            'simple_limit': 3000000,
            'reduced_limit': 2000000,
            'simple_limit_rounded': 2800000,
            'reduced_limit_rounded': 2500000,
            'max_limit': 4000000,
            'set_limit': 3000000,
            'limit_adjustment_factor': 1.0,
        }

        CreditLimitGenerationFactory(
            account=self.account, application=self.application,
            max_limit=1000000, set_limit=1000000,
            credit_matrix=self.credit_matrix,
            log=json.dumps({
                "simple_limit": 1800000,
                "reduced_limit": 1600000
            })
        )

        update_account_max_limit_pre_matrix_with_cfs(self.application, self.affordability_history)

        # Credit limit generation created
        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=self.application, reason=CreditLimitGenerationReason.UPDATE_MONTHLY_INCOME
        ).last()
        self.assertEqual(last_credit_generation.max_limit, 1000000)
        self.assertEqual(last_credit_generation.set_limit, 1000000)
        credit_limit_generation_log = json.loads(last_credit_generation.log)
        self.assertEqual(credit_limit_generation_log['max_limit (pre-matrix)'], 2800000)
        self.assertEqual(credit_limit_generation_log['set_limit (pre-matrix)'], 2500000)


class TestGetTripePGoodLimit(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.eligible_check = EligibleCheckFactory(
            check_name="eligible_limit_increase",
            application_id=self.application.id,
            parameter={"limit_gain": 5000000},
        )

    def test_is_not_okay(self):
        self.eligible_check.is_okay = False
        self.eligible_check.save()

        max_limit, set_limit = get_triple_pgood_limit(self.application, 4000000, 4000000)
        self.assertEqual(max_limit, 4000000)
        self.assertEqual(set_limit, 4000000)

    def test_has_no_parameter(self):
        self.eligible_check.parameter = None
        self.eligible_check.save()

        max_limit, set_limit = get_triple_pgood_limit(self.application, 4000000, 4000000)
        self.assertEqual(max_limit, 4000000)
        self.assertEqual(set_limit, 4000000)

    def test_has_no_limit_gain_in_parameter(self):
        self.eligible_check.parameter = {}
        self.eligible_check.save()

        max_limit, set_limit = get_triple_pgood_limit(self.application, 4000000, 4000000)
        self.assertEqual(max_limit, 4000000)
        self.assertEqual(set_limit, 4000000)

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.account.services.credit_limit.is_inside_premium_area', return_value=True)
    @patch('juloserver.account.services.credit_limit.get_credit_pgood', return_value=0.96)
    def test_first_condition(self, heimdall, is_premium_area, is_salaried):
        max_limit, set_limit = get_triple_pgood_limit(self.application, 16100000, 16100000)
        self.assertEqual(max_limit, 21000000)
        self.assertEqual(set_limit, 21000000)

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.account.services.credit_limit.is_inside_premium_area', return_value=True)
    @patch('juloserver.account.services.credit_limit.get_credit_pgood', return_value=0.91)
    def test_2nd_condition(self, heimdall, is_premium_area, is_salaried):
        max_limit, set_limit = get_triple_pgood_limit(self.application, 14100000, 14100000)
        self.assertEqual(max_limit, 19000000)
        self.assertEqual(set_limit, 19000000)

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.account.services.credit_limit.is_inside_premium_area', return_value=True)
    @patch('juloserver.account.services.credit_limit.get_credit_pgood', return_value=0.81)
    def test_3rd_condition(self, heimdall, is_premium_area, is_salaried):
        max_limit, set_limit = get_triple_pgood_limit(self.application, 4100000, 4100000)
        self.assertEqual(max_limit, 9000000)
        self.assertEqual(set_limit, 9000000)

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.account.services.credit_limit.is_inside_premium_area', return_value=False)
    @patch('juloserver.account.services.credit_limit.get_credit_pgood', return_value=0.96)
    def test_4th_condition(self, heimdall, is_premium_area, is_salaried):
        max_limit, set_limit = get_triple_pgood_limit(self.application, 14100000, 14100000)
        self.assertEqual(max_limit, 19000000)
        self.assertEqual(set_limit, 19000000)

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.account.services.credit_limit.is_inside_premium_area', return_value=False)
    @patch('juloserver.account.services.credit_limit.get_credit_pgood', return_value=0.81)
    def test_5th_condition(self, heimdall, is_premium_area, is_salaried):
        max_limit, set_limit = get_triple_pgood_limit(self.application, 4100000, 4100000)
        self.assertEqual(max_limit, 9000000)
        self.assertEqual(set_limit, 9000000)

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.account.services.credit_limit.is_inside_premium_area', return_value=True)
    @patch('juloserver.account.services.credit_limit.get_credit_pgood', return_value=0.91)
    def test_no_condition_match(self, heimdall, is_premium_area, is_salaried):
        max_limit, set_limit = get_triple_pgood_limit(self.application, 3100000, 3100000)
        self.assertEqual(max_limit, 8100000)
        self.assertEqual(set_limit, 8100000)


class TestGetNonFDCJobFailedLimit(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.HIGH_RISK, parameters={"cap_limit": 500_000}
        )
        self.application = ApplicationFactory()
        self.eligible_check = EligibleCheckFactory(
            application_id=self.application.id, check_name="non_fdc_job_check_fail"
        )

    def test_feature_disabled_return_original_limit(self):
        self.setting.is_active = False
        self.setting.save()

        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 1_000_000, 1_000_000)
        self.assertEqual(ml, 1_000_000)
        self.assertEqual(sl, 1_000_000)

    def test_feature_not_exists_return_original_limit(self):
        self.setting.delete()

        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 1_000_000, 1_000_000)
        self.assertEqual(ml, 1_000_000)
        self.assertEqual(sl, 1_000_000)

    def test_feature_wrong_configured_return_original_limit(self):
        self.setting.parameters = {"caped_baldy": 500_000}
        self.setting.save()

        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 1_000_000, 1_000_000)
        self.assertEqual(ml, 1_000_000)
        self.assertEqual(sl, 1_000_000)

    def test_has_no_eligible_check_return_original_limit(self):
        self.eligible_check.delete()

        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 1_000_000, 1_000_000)
        self.assertEqual(ml, 1_000_000)
        self.assertEqual(sl, 1_000_000)

    def test_max_limit_less_than_threshold_return_original_limit(self):
        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 300_000, 1_000_000)
        self.assertEqual(ml, 300_000)
        self.assertEqual(sl, 1_000_000)

    def test_set_limit_less_than_threshold_return_original_limit(self):
        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 1_000_000, 200_000)
        self.assertEqual(ml, 1_000_000)
        self.assertEqual(sl, 200_000)

    def test_max_and_set_limit_greater_than_threshold_return_threshold(self):
        ml, sl = get_non_fdc_job_check_fail_limit(self.application, 1_000_000, 1_000_000)
        self.assertEqual(ml, 500_000)
        self.assertEqual(sl, 500_000)
