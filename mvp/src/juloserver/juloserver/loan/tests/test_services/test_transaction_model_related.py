import datetime
import json
from datetime import timedelta
from mock import MagicMock, patch

from django.test import TestCase

from juloserver.ana_api.services import LoanSelectionAnaAPIPayload, TransactionModelResult
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.loan.constants import LoanFeatureNameConst, LoanRedisKey
from juloserver.loan.exceptions import TransactionModelException
from juloserver.loan.models import (
    TransactionModelCustomer,
    TransactionModelCustomerAnaHistory,
    TransactionModelCustomerHistory,
)
from juloserver.loan.services.feature_settings import AnaTransactionModelSetting
from juloserver.loan.services.transaction_model_related import (
    MercuryCustomerService,
    TransactionModelHistoryData,
    create_transaction_model_history,
    get_customer_outstanding_cashloan_amount,
)
from juloserver.loan.tests.factories import TransactionModelCustomerFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.qris.services.core_services import create_transaction_history


class TestCalculateAnaAvailableCashloanAmount(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            available_limit=5_000_000,
        )

        self.inactive_cash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            loan_amount=2_000_000,
        )
        self.inactive_noncash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.HEALTHCARE.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            loan_amount=2_200_000,
        )
        self.failed_cash_loan_2 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.TRANSACTION_FAILED),
            loan_amount=500_000,
        )


class TestGetCustomerOutstandingCashloanAmount(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )

    def test_get_customer_outstanding_cashloan_amount_multiloan(self):
        # set up

        self.draft_cash_loan_0 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            loan_amount=2_050_000,
        )
        self.draft_noncash_loan_0 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.LISTRIK_PLN.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            loan_amount=210_000,
        )
        self.current_cash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=2_000_000,
        )
        self.current_noncash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.HEALTHCARE.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=2_200_000,
        )
        self.to_disbursed_cash_loan_2 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            loan_amount=3_000_000,
        )

        self.to_disbursed_noncash_loan_2 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.QRIS_1.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            loan_amount=1_000_000,
        )

        self.failed_cash_loan_3 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.TRANSACTION_FAILED),
            loan_amount=1_300_000,
        )
        self.failed_noncash_loan_3 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.EDUCATION.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.TRANSACTION_FAILED),
            loan_amount=1_300_000,
        )

        self.paidoff_cash_loan_4 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            loan_amount=1_500_000,
        )
        self.paidoff_noncash_loan_4 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            loan_amount=1_700_000,
        )

        self.cancelled_cash_loan_5 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER),
            loan_amount=3_500_000,
        )
        self.cancelled_noncash_loan_5 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER),
            loan_amount=350_000,
        )
        self.selloff_cash_loan_5 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.SELL_OFF),
            loan_amount=500_000,
        )
        self.selloff_noncash_loan_5 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.SELL_OFF),
            loan_amount=320_000,
        )
        self.late_cash_loan_6 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_90DPD),
            loan_amount=323_000,
        )

        # call func()
        outstanding_cashloan_amount = get_customer_outstanding_cashloan_amount(
            customer_id=self.customer.id,
        )

        # assert
        expected_cashloan_amount = (
            self.current_cash_loan_1.loan_amount
            + self.late_cash_loan_6.loan_amount
            + self.to_disbursed_cash_loan_2.loan_amount
        )
        self.assertEqual(outstanding_cashloan_amount, expected_cashloan_amount)

    def test_get_customer_outstanding_cashloan_amount_no_active_loan(self):
        self.paidoff_cash_loan_4 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            loan_amount=1_500_000,
        )

        # call func()
        outstanding_cashloan_amount = get_customer_outstanding_cashloan_amount(
            customer_id=self.customer.id,
        )

        self.assertEqual(0, outstanding_cashloan_amount)

    def test_get_customer_outstanding_cashloan_amount_with_date(self):
        """
        Only include amount from certain date
        """
        last_mercury_true_date = datetime.datetime(2024, 9, 30, 10, 13, 0)

        self.current_ongoing_cash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=2_300_000,
        )
        self.current_ongoing_cash_loan_1.cdate = last_mercury_true_date + timedelta(minutes=1)
        self.current_ongoing_cash_loan_1.save()

        self.past_ongoing_cash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=2_100_000,
        )
        self.past_ongoing_cash_loan_1.cdate = last_mercury_true_date - timedelta(minutes=1)
        self.past_ongoing_cash_loan_1.save()

        outstanding_cashloan_amount = get_customer_outstanding_cashloan_amount(
            customer_id=self.customer.id,
            last_mercury_true_date=last_mercury_true_date,
        )

        self.assertEqual(
            outstanding_cashloan_amount,
            self.current_ongoing_cash_loan_1.loan_amount,
        )

        # new loan (other)
        self.current_ongoing_cash_loan_2 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=2_330_000,
        )
        self.current_ongoing_cash_loan_2.cdate = last_mercury_true_date + timedelta(days=1)
        self.current_ongoing_cash_loan_2.save()

        outstanding_cashloan_amount = get_customer_outstanding_cashloan_amount(
            customer_id=self.customer.id,
            last_mercury_true_date=last_mercury_true_date,
        )

        self.assertEqual(
            outstanding_cashloan_amount,
            self.current_ongoing_cash_loan_1.loan_amount
            + self.current_ongoing_cash_loan_2.loan_amount,
        )

class TestMercuryCustomerService(TestCase):
    def setUp(self) -> None:
        self.fake_redis = MockRedisHelper()
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.ANA_TRANSACTION_MODEL,
            is_active=True,
            parameters={
                "cooldown_time_in_seconds": AnaTransactionModelSetting.DEFAULT_COOLDOWN_TIME,
                "request_to_ana_timeout_in_seconds": AnaTransactionModelSetting.DEFAULT_REQUEST_TIMEOUT,
                "whitelist_settings": {
                    "is_whitelist_active": False,
                    "whitelist_by_customer_id": [],
                    "whitelist_by_last_digit": [],
                },
                "is_hitting_ana": True,
                "minimum_limit_to_hit_ana": AnaTransactionModelSetting.MINIMUM_LIMIT_TO_HIT_ANA,
            },
        )
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
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()

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

        self.fake_redis = MockRedisHelper()
        self.service = MercuryCustomerService(
            account=self.account,
        )

    @patch(
        "juloserver.loan.services.transaction_model_related.MercuryCustomerService.calculate_ana_available_cashloan_amount"
    )
    def test_is_mercury_customer_blocked(self, mock_calculate_cashloan_amount):
        min_amount_threshold = 100_000
        parameters = {
            "whitelist": {"is_active": False, "customer_ids": []},
            "dbr_loan_amount_default": 2_000_000,
            "min_amount_threshold": min_amount_threshold,
        }
        self.loan_amount_config = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_AMOUNT_DEFAULT_CONFIG,
            is_active=True,
            parameters=parameters,
        )

        # case not blocked, available_cashloan is exact minimum
        mock_calculate_cashloan_amount.return_value = min_amount_threshold
        self.assertEqual(
            self.service.is_mercury_customer_blocked(),
            False,
        )

        # case blocked
        mock_calculate_cashloan_amount.return_value = min_amount_threshold - 1
        self.assertEqual(
            self.service.is_mercury_customer_blocked(),
            True,
        )

    def test_compute_mercury_tenures(self):
        """
        Cases: https://docs.google.com/spreadsheets/d/1Qc8EFVysZXf3rRryaQJxhQT29kw14FFBR__TWtDBwTI/edit?usp=sharing
        """

        # case 1
        final_tenures = [5, 6, 7, 8, 9]
        mercury_loan_tenures = [4, 5]

        result = self.service.compute_mercury_tenures(
            final_tenures=final_tenures,
            mercury_loan_tenures=mercury_loan_tenures,
        )

        self.assertEqual(result, [5])

        # case 2
        final_tenures = [1, 2]
        mercury_loan_tenures = [3, 4]

        result = self.service.compute_mercury_tenures(
            final_tenures=final_tenures,
            mercury_loan_tenures=mercury_loan_tenures,
        )

        self.assertEqual(result, [1, 2])

        # case 3
        final_tenures = [5, 6]
        mercury_loan_tenures = [3, 4]

        result = self.service.compute_mercury_tenures(
            final_tenures=final_tenures,
            mercury_loan_tenures=mercury_loan_tenures,
        )

        self.assertEqual(result, [5, 6])

        # case 4
        final_tenures = [3, 4]
        mercury_loan_tenures = [4, 5]

        result = self.service.compute_mercury_tenures(
            final_tenures=final_tenures,
            mercury_loan_tenures=mercury_loan_tenures,
        )

        self.assertEqual(result, [3, 4])

        # case 5
        final_tenures = [3, 4, 5]
        mercury_loan_tenures = [2, 3, 4]

        result = self.service.compute_mercury_tenures(
            final_tenures=final_tenures,
            mercury_loan_tenures=mercury_loan_tenures,
        )

        self.assertEqual(result, [3, 4])

        # case 6
        final_tenures = [3, 4, 5, 6, 7, 8]
        mercury_loan_tenures = [1, 2, 3, 4, 5]

        result = self.service.compute_mercury_tenures(
            final_tenures=final_tenures,
            mercury_loan_tenures=mercury_loan_tenures,
        )

        self.assertEqual(result, [3, 4, 5])

    def test_transaction_method_valid(self):
        # tarik (self)
        is_valid = self.service.is_method_name_valid(
            method_name=TransactionMethodCode.SELF.name,
        )
        self.assertEqual(is_valid, True)
        is_valid = self.service.is_method_valid(
            method_code=TransactionMethodCode.SELF.code,
        )
        self.assertEqual(is_valid, True)

        # kirim (to other)
        is_valid = self.service.is_method_name_valid(
            method_name=TransactionMethodCode.OTHER.name,
        )
        self.assertEqual(is_valid, True)
        is_valid = self.service.is_method_valid(
            method_code=TransactionMethodCode.OTHER.code,
        )
        self.assertEqual(is_valid, True)

        # non cash
        is_valid = self.service.is_method_name_valid(
            method_name=TransactionMethodCode.QRIS_1.name,
        )
        self.assertEqual(is_valid, False)
        is_valid = self.service.is_method_valid(
            method_code=TransactionMethodCode.QRIS_1.code,
        )
        self.assertEqual(is_valid, False)

    def test_is_customer_eligible(self):
        # non j1/turbo
        self.application.product_line_id = ProductLineCodes.AXIATA1
        self.application.save()

        is_eligible = self.service.is_customer_eligible()
        self.assertEqual(is_eligible, False)

        # j1
        self.application.product_line_id = ProductLineCodes.J1
        self.application.save()
        is_eligible = self.service.is_customer_eligible()
        self.assertEqual(is_eligible, True)

        # not need for turbo for now
        # self.application.product_line_id = ProductLineCodes.J1
        # self.application.save()
        # is_eligible = self.service.is_customer_eligible()
        # self.assertEqual(is_eligible, True)

    def test_calculate_ana_available_cashloan_amount(self):
        # set up
        max_cashloan_amount = 10_000_000
        model = TransactionModelCustomerFactory(
            customer_id=self.customer.id,
            allowed_loan_duration=[],
            max_cashloan_amount=max_cashloan_amount,
            is_mercury=True,
        )
        # doesn't have history
        self.service._refresh_transaction_model_object()
        with self.assertRaises(TransactionModelException):
            self.service.calculate_ana_available_cashloan_amount()

        # with history, no loan
        create_transaction_model_history(
            [
                TransactionModelHistoryData(
                    old_value='',
                    new_value=True,
                    field_name='is_mercury',
                    transaction_model_customer_id=model.id,
                )
            ]
        )
        result = self.service.calculate_ana_available_cashloan_amount()

        self.assertEqual(
            result,
            max_cashloan_amount,
        )

        # with ongoing loan (created after history above)
        current_ongoing_cash_loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=2_300_000,
        )
        result = self.service.calculate_ana_available_cashloan_amount()
        self.assertEqual(result, max_cashloan_amount - current_ongoing_cash_loan_1.loan_amount)

    @patch(
        "juloserver.loan.services.transaction_model_related.MercuryCustomerService.hit_ana_loan_selection_api"
    )
    @patch(
        "juloserver.loan.services.transaction_model_related.MercuryCustomerService.calculate_ana_available_cashloan_amount"
    )
    def test_get_mercury_available_limit_case_not_hit_ana(self, mock_calculate, mock_hit_ana_api):
        # case outstanding > 0
        tarik_loan = LoanFactory(
            loan_amount=999_999,
            account=self.account_limit.account,
            credit_matrix=self.credit_matrix,
            product=self.credit_matrix.product,
            customer=self.customer,
            transaction_method_id=TransactionMethodCode.SELF.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
        )
        model = TransactionModelCustomerFactory(
            customer_id=self.customer.id,
            allowed_loan_duration=[],
            max_cashloan_amount=10_000_000,
            is_mercury=True,
        )
        self.service._refresh_transaction_model_object()
        available_limt = 1_050_000
        mock_calculate.return_value = available_limt
        is_applied, new_available_limit = self.service.get_mercury_available_limit(
            self.account_limit,
            min_duration=1,
            max_duration=2,
            transaction_type=TransactionMethodCode.SELF.name,
        )
        self.assertEqual(is_applied, True)
        self.assertEqual(new_available_limit, available_limt)
        mock_hit_ana_api.assert_not_called()

        # case outstanding <= 0 (not having outstanding amount)
        tarik_loan.loan_status_id = LoanStatusCodes.PAID_OFF
        tarik_loan.save()

        is_applied, new_available_limit = self.service.get_mercury_available_limit(
            self.account_limit,
            min_duration=1,
            max_duration=2,
            transaction_type=TransactionMethodCode.SELF.name,
        )
        self.assertEqual(is_applied, False)
        self.assertEqual(new_available_limit, self.account_limit.available_limit)
        mock_hit_ana_api.assert_not_called()

        model.refresh_from_db()
        self.assertEqual(model.is_mercury, False)
        history_exists = TransactionModelCustomerHistory.objects.filter(
            transaction_model_customer_id=model.id,
            field_name='is_mercury',
            old_value='True',
            new_value='False',
        ).exists()
        self.assertEqual(True, history_exists)

    @patch(
        "juloserver.loan.services.transaction_model_related.MercuryCustomerService.hit_ana_loan_selection_api"
    )
    @patch(
        "juloserver.loan.services.transaction_model_related.MercuryCustomerService.calculate_ana_available_cashloan_amount"
    )
    def test_get_mercury_available_limit_case_hit_ana(self, mock_calculate, mock_hit_ana_api):
        expected_new_cashloan_limit = 3_000_000
        mock_calculate.return_value = expected_new_cashloan_limit

        def _create_model():
            TransactionModelCustomerFactory(
                customer_id=self.customer.id,
                allowed_loan_duration=[],
                max_cashloan_amount=10_000_000,
                is_mercury=True,
            )

        # model doesn't exist
        # case no result from ana
        mock_hit_ana_api.return_value = None
        is_applied, new_available_limit = self.service.get_mercury_available_limit(
            self.account_limit,
            min_duration=1,
            max_duration=2,
            transaction_type=TransactionMethodCode.SELF.name,
        )
        self.assertEqual(is_applied, False)
        self.assertEqual(new_available_limit, self.account_limit.available_limit)

        # case with result from ana, mercury is False
        max_cashloan_amount1 = 3_000_000
        ana_json_response_1 = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": False,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": max_cashloan_amount1,
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }
        ana_model_result = TransactionModelResult(**ana_json_response_1)
        mock_hit_ana_api.return_value = ana_model_result
        is_applied, new_available_limit = self.service.get_mercury_available_limit(
            self.account_limit,
            min_duration=1,
            max_duration=2,
            transaction_type=TransactionMethodCode.SELF.name,
        )
        self.assertEqual(is_applied, False)
        self.assertEqual(new_available_limit, self.account_limit.available_limit)

        # case with result from ana, mercury is True
        max_cashloan_amount1 = 3_000_000
        ana_json_response_1 = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": max_cashloan_amount1,
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }
        ana_model_result = TransactionModelResult(**ana_json_response_1)
        mock_hit_ana_api.return_value = ana_model_result
        mock_hit_ana_api.side_effect = _create_model()

        is_applied, new_available_limit = self.service.get_mercury_available_limit(
            self.account_limit,
            min_duration=1,
            max_duration=2,
            transaction_type=TransactionMethodCode.SELF.name,
        )
        self.assertEqual(is_applied, True)
        self.assertEqual(new_available_limit, expected_new_cashloan_limit)

    def test_update_or_create_transaction_model_customer(self):
        # set-up, create some cashloan
        available_limit = 5_000_000
        self.account_limit.available_limit = available_limit
        self.account_limit.save()

        # 1. no model record yet => create one; lets start with 'false' status
        max_cashloan_amount1 = 4_000_000
        ana_json_response_1 = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": False,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": max_cashloan_amount1,
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }

        is_created, returned_model = self.service.update_or_create_transaction_model_customer(
            customer_id=self.customer.id,
            ana_model_result=TransactionModelResult(**ana_json_response_1),
        )
        self.assertTrue(is_created)

        model = TransactionModelCustomer.objects.filter(customer_id=self.customer.id).last()
        self.assertIsNotNone(model)
        self.assertEqual(model, returned_model)
        self.assertEqual(
            model.allowed_loan_duration,
            ana_json_response_1['allowed_loan_duration_amount']['loan_duration_range'],
        )
        self.assertEqual(
            model.max_cashloan_amount,
            ana_json_response_1['allowed_loan_duration_amount']['max_cashloan_amount'],
        )
        self.assertEqual(model.is_mercury, ana_json_response_1['is_mercury'])
        self.assertEqual(
            TransactionModelCustomerAnaHistory.objects.filter(customer_id=self.customer.id).count(),
            1,
        )
        self.assertEqual(
            TransactionModelCustomerHistory.objects.filter(
                transaction_model_customer_id=model.id
            ).count(),
            3,
        )

        # 2. hit again gain, ana returns another 'false'
        # we don't update, since it's another 'false'; data should be same
        self.service._refresh_transaction_model_object()  # refresh from db
        max_cashloan_amount2 = 3_500_000
        ana_json_response_2 = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": False,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": max_cashloan_amount2,
                "loan_duration_range": [5, 6, 7, 8, 9, 10, 11, 12],
            },
        }

        is_created, returned_model = self.service.update_or_create_transaction_model_customer(
            customer_id=self.customer.id,
            ana_model_result=TransactionModelResult(**ana_json_response_2),
        )
        self.assertFalse(is_created)

        model = TransactionModelCustomer.objects.filter(customer_id=self.customer.id).last()
        self.assertIsNotNone(model)
        self.assertEqual(model, returned_model)

        self.assertEqual(
            model.allowed_loan_duration,
            ana_json_response_1['allowed_loan_duration_amount']['loan_duration_range'],
        )
        self.assertEqual(
            model.max_cashloan_amount,
            ana_json_response_1['allowed_loan_duration_amount']['max_cashloan_amount'],
        )
        self.assertEqual(model.is_mercury, ana_json_response_1['is_mercury'])
        self.assertEqual(
            TransactionModelCustomerAnaHistory.objects.filter(customer_id=self.customer.id).count(),
            1,
        )
        self.assertEqual(
            TransactionModelCustomerHistory.objects.filter(
                transaction_model_customer_id=model.id
            ).count(),
            3,
        )

        # 3. hit again gain, ana returns 'mercury' true
        # only save different fields
        self.service._refresh_transaction_model_object()  # refresh from db
        max_cashloan_amount3 = 3_000_000
        ana_json_response_3 = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": max_cashloan_amount3,
                "loan_duration_range": [
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    10,
                    11,
                    12,
                ],  # same as first previous
            },
        }

        is_created, returned_model = self.service.update_or_create_transaction_model_customer(
            customer_id=self.customer.id,
            ana_model_result=TransactionModelResult(**ana_json_response_3),
        )
        self.assertFalse(is_created)

        model = TransactionModelCustomer.objects.filter(customer_id=self.customer.id).last()
        self.assertIsNotNone(model)
        self.assertEqual(model, returned_model)

        self.assertEqual(
            model.allowed_loan_duration,
            ana_json_response_3['allowed_loan_duration_amount']['loan_duration_range'],
        )
        self.assertEqual(
            model.max_cashloan_amount,
            ana_json_response_3['allowed_loan_duration_amount']['max_cashloan_amount'],
        )
        self.assertTrue(model.is_mercury)
        self.assertEqual(model.is_mercury, ana_json_response_3['is_mercury'])
        self.assertEqual(
            TransactionModelCustomerAnaHistory.objects.filter(customer_id=self.customer.id).count(),
            2,
        )
        self.assertEqual(
            TransactionModelCustomerHistory.objects.filter(
                transaction_model_customer_id=model.id
            ).count(),
            3 + 2,  # 2 more fields: is_mercury, max_cashloan_amount
        )

        # 4. After this, user's mercury status is true, nothing should happen
        self.service._refresh_transaction_model_object()  # refresh from db
        with self.assertRaises(TransactionModelException):
            self.service.update_or_create_transaction_model_customer(
                customer_id=self.customer.id,
                ana_model_result=TransactionModelResult(**ana_json_response_2),
            )

        # history doesn't change; like previous
        self.assertEqual(
            TransactionModelCustomerAnaHistory.objects.filter(customer_id=self.customer.id).count(),
            2,
        )
        self.assertEqual(
            TransactionModelCustomerHistory.objects.filter(
                transaction_model_customer_id=model.id
            ).count(),
            3 + 2,
        )

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_whitelist_hit_ana_loan_section_api(self, mock_get_redis, mock_predict_loan_selection):
        # setup
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        mock_get_redis.return_value = self.fake_redis
        mock_predict_loan_selection.return_value = None, None

        # case whitelist active is off
        service = MercuryCustomerService(account=self.account)
        service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )

        mock_predict_loan_selection.assert_called_once()
        mock_predict_loan_selection.reset_mock()

        # case whitelist ON, no customer/digits specified
        self.fs.parameters['whitelist_settings']['is_whitelist_active'] = True
        self.fs.save()

        service = MercuryCustomerService(account=self.account)
        service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_predict_loan_selection.assert_not_called()
        mock_predict_loan_selection.reset_mock()

        # case whitelist ON, with customer id
        self.fs.parameters['whitelist_settings']['whitelist_by_customer_id'] = [self.customer.id]
        self.fs.save()

        service = MercuryCustomerService(account=self.account)
        service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_predict_loan_selection.assert_called_once()
        mock_predict_loan_selection.reset_mock()

        # case whitelist ON, with last digit
        customer_last_digit = self.customer.id % 10
        self.fs.parameters['whitelist_settings']['whitelist_by_customer_id'] = []
        self.fs.parameters['whitelist_settings']['whitelist_by_last_digit'] = [customer_last_digit]
        self.fs.save()

        service = MercuryCustomerService(account=self.account)
        service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_predict_loan_selection.assert_called_once()

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_section_api_redis_key_exists(
        self, mock_get_redis, mock_predict_loan_selection
    ):
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        response_data = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": self.account_limit.available_limit - 1,  # max cashloan limit
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }
        model_result = TransactionModelResult(**response_data)
        cooldown_time = 60 * 10
        # make redis key
        key = LoanRedisKey.ANA_TRANSACTION_MODEL_COOLDOWN.format(
            customer_id=self.customer.id,
            payload_hash=hash(payload),
        )
        self.fake_redis.set(
            key=key,
            value=json.dumps(model_result.__dict__),
            expire_time=timedelta(cooldown_time),
        )
        mock_get_redis.return_value = self.fake_redis

        self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_predict_loan_selection.assert_not_called()

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_section_api_redis_expires(
        self, mock_get_redis, mock_predict_loan_selection
    ):
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        cooldown_time = 10
        # make redis key
        key = LoanRedisKey.ANA_TRANSACTION_MODEL_COOLDOWN.format(
            customer_id=self.customer.id,
            payload_hash=hash(payload),
        )
        mock_get_redis.return_value = self.fake_redis

        response_dict = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": self.account_limit.available_limit - 1,  # max cashloan limit
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }
        model_result = TransactionModelResult(
            **response_dict,
        )
        self.fake_redis.set(
            key=key,
            value=json.dumps(model_result.__dict__),
            expire_time=timedelta(seconds=cooldown_time),
        )

        self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_predict_loan_selection.assert_not_called()
        mock_predict_loan_selection.reset_mock()

        # delete key
        self.fake_redis.delete_key(key)
        mock_predict_loan_selection.return_value = False, None

        self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_predict_loan_selection.assert_called_once_with(payload=payload)

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_section_api_ok(self, mock_get_redis, mock_predict_loan_selection):
        """
        Case ok with no redis key set
        """
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        # make redis key
        key = LoanRedisKey.ANA_TRANSACTION_MODEL_COOLDOWN.format(
            customer_id=self.customer.id,
            payload_hash=hash(payload),
        )
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.exists.return_value = False

        response_dict = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": self.account_limit.available_limit - 1,  # max cashloan limit
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }
        model_result = TransactionModelResult(
            **response_dict,
        )

        # case with prediction, 200
        mock_predict_loan_selection.return_value = True, model_result
        self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )

        newly_created_model = TransactionModelCustomer.objects.filter(
            customer_id=self.customer.id,
        ).last()

        self.assertIsNotNone(newly_created_model)

        mock_redis.set.assert_called_once_with(
            key=key,
            value=json.dumps(model_result.__dict__),
            expire_time=timedelta(seconds=self.fs.parameters['cooldown_time_in_seconds']),
        )
        mock_predict_loan_selection.assert_called_once_with(
            payload=payload,
        )

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_section_api_case_max_limit_larger_than_available_limit(
        self, mock_get_redis, mock_predict_loan_selection
    ):

        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        # make redis key
        key = LoanRedisKey.ANA_TRANSACTION_MODEL_COOLDOWN.format(
            customer_id=self.customer.id,
            payload_hash=hash(payload),
        )
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.exists.return_value = False

        response_dict = {
            "prediction_time": "2024-12-04 02:45:12.247196 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": self.account_limit.available_limit
                + 100,  # max cashloan limit
                "loan_duration_range": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            },
        }
        model_result = TransactionModelResult(
            **response_dict,
        )

        # case with prediction, 200
        mock_predict_loan_selection.return_value = True, model_result
        result = self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        self.assertIsNone(result)

        newly_created_model = TransactionModelCustomer.objects.filter(
            customer_id=self.customer.id,
        ).last()

        self.assertIsNone(newly_created_model)

        mock_predict_loan_selection.assert_called_once_with(
            payload=payload,
        )
        mock_redis.set.assert_not_called()

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_section_api_case_no_prediction_data(
        self, mock_get_redis, mock_predict_loan_selection
    ):
        """
        Case ana responds with 204 (ok but no prediction)
        """
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        # make redis key
        key = LoanRedisKey.ANA_TRANSACTION_MODEL_COOLDOWN.format(
            customer_id=self.customer.id,
            payload_hash=hash(payload),
        )
        mock_get_redis.return_value = self.fake_redis

        # case success with prediction, 204
        mock_predict_loan_selection.return_value = True, None
        result = self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        self.assertIsNone(result)
        mock_predict_loan_selection.assert_called_once()
        # assert set redis key
        self.assertTrue(self.fake_redis.exists(names=key))

        # called one more time, will hit redis cache
        mock_get_redis.reset_mock()
        mock_get_redis.return_value = self.fake_redis
        mock_predict_loan_selection.reset_mock()
        result = self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        self.assertIsNone(result)
        mock_get_redis.assert_called_once()
        mock_predict_loan_selection.assert_not_called()

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_section_api_bad_response_status(
        self, mock_get_redis, mock_predict_loan_selection
    ):
        """
        Case ana returns bad status [non 2xx]
        """
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.exists.return_value = False

        response_data = None
        mock_predict_loan_selection.return_value = False, response_data
        self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )
        mock_redis.set.assert_not_called()
        mock_predict_loan_selection.assert_called_once_with(
            payload=payload,
        )

    @patch('juloserver.loan.services.transaction_model_related.predict_loan_selection')
    @patch('juloserver.loan.services.transaction_model_related.get_redis_client')
    def test_hit_ana_loan_selection_api_case_less_than_minimum_limit(
        self, mock_get_redis, mock_predict_loan_selection
    ):
        # set up
        self.fs.is_active = True
        self.fs.save()

        # case available limit isn't enough
        self.account_limit.available_limit = AnaTransactionModelSetting.MINIMUM_LIMIT_TO_HIT_ANA - 1
        self.account_limit.save()

        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        result = self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )

        self.assertEqual(result, None)

        mock_get_redis.assert_not_called()
        mock_predict_loan_selection.assert_not_called()

        # case available limit is enough

        self.account_limit.available_limit = AnaTransactionModelSetting.MINIMUM_LIMIT_TO_HIT_ANA + 1
        self.account_limit.save()

        # re-init mocks
        mock_get_redis.reset_mock()
        mock_predict_loan_selection.reset_mock()

        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.exists.return_value = False

        response_data = None
        mock_predict_loan_selection.return_value = False, response_data

        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.max_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        self.service.hit_ana_loan_selection_api(
            payload=payload,
            account_limit=self.account_limit,
        )

        mock_get_redis.assert_called_once()
        mock_predict_loan_selection.assert_called_once_with(
            payload=payload,
        )
