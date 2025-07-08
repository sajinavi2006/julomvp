from datetime import timedelta
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
)

from juloserver.loan.services.adjusted_loan_matrix import (
    get_adjusted_total_interest_rate,
    get_daily_max_fee,
    validate_max_fee_rule_by_loan_requested,
    validate_max_fee_rule,
    get_global_cap_for_tenure_threshold
)


class TestServiceAdjustLoanMatrix(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            is_active=False,
            parameters={"daily_max_fee": 0.2},
        )
        self.current_ts = timezone.localtime(timezone.now())

    def test_get_daily_max_fee(self):
        self.assertIsNone(get_daily_max_fee())

        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.assertEqual(get_daily_max_fee(), float(0.002))

    def test_validate_max_fee_rule_by_loan_requested(self):
        """
        if exceeded, take insurance out of the equation
        """
        expected_insurance_rate = 0

        self.feature_setting.parameters = {"daily_max_fee": 0.02}
        self.feature_setting.is_active = True
        self.feature_setting.save()
        return_value = validate_max_fee_rule_by_loan_requested(
            (self.current_ts + timedelta(days=20)).date(),
            {
                "interest_rate_monthly": 0.05,
                "loan_duration_request": 1,
                "provision_fee": 0.08,
                "insurance_premium": 6500,
                "loan_amount": 1_000_000,
            },
            {}
        )
        expected_interest_rate = 0
        expected_total_fee_rate = 0.004
        self.assertEqual(return_value[0], True)
        self.assertEqual(return_value[2], expected_total_fee_rate)
        self.assertEqual(return_value[3], expected_interest_rate)
        self.assertEqual(return_value[4], expected_insurance_rate)

        return_value = validate_max_fee_rule_by_loan_requested(
            (self.current_ts + timedelta(days=10)).date(),
            {
                'interest_rate_monthly': 0.10,
                'loan_duration_request': 3,
                'provision_fee': 0.06,
                'insurance_premium': 6500,
                'loan_amount': 1000000
            },
            {}
        )
        expected_interest_rate = 0
        expected_total_fee_rate = 0.014
        self.assertEqual(return_value[0], True)
        self.assertEqual(return_value[2], expected_total_fee_rate)
        self.assertEqual(return_value[3], expected_interest_rate)
        self.assertEqual(return_value[4], expected_insurance_rate)

    def test_validate_max_fee_rule(self):
        return_value = validate_max_fee_rule(self.current_ts.date(), 0.05, 1, 0.08, 0, 0, {})
        self.assertEqual(return_value[0], False)

        self.feature_setting.is_active = True
        self.feature_setting.save()
        return_value = validate_max_fee_rule(
            self.current_ts.date(),
            0.05,
            1,
            0.08,
            0,
            0,
            {'is_buku_warung': True, 'duration_in_days': 20},
        )
        self.assertEqual(return_value[0], True)
        self.assertEqual(return_value[1], 0.08)
        self.assertEqual(return_value[2], 0.04)
        self.assertEqual(return_value[3], 0.04)
        self.assertEqual(return_value[4], 0.0)

    def test_adjusted_total_interest_rate_case_positive(self):
        max_fee = 0.06
        provision_fee = 0.03
        insurance_rate = 0.01

        (
            result_total_interest,
            result_provision,
            result_insurance,
        ) = get_adjusted_total_interest_rate(
            max_fee=max_fee, provision_fee=provision_fee, insurance_premium_rate=insurance_rate
        )

        assert result_total_interest == 0.02
        assert result_provision == 0.03
        assert result_insurance == 0.01

    def test_adjusted_total_interest_rate_case_negative_total_interest(self):
        max_fee = 0.06
        provision_fee = 0.07
        insurance_rate = 0.01

        (
            result_total_interest,
            result_provision,
            result_insurance,
        ) = get_adjusted_total_interest_rate(
            max_fee=max_fee, provision_fee=provision_fee, insurance_premium_rate=insurance_rate
        )

        assert result_total_interest == 0
        assert result_provision == 0.05
        assert result_insurance == 0.01

    def test_adjusted_total_interest_rate_case_negative_provision_rate(self):
        max_fee = 0.06
        provision_fee = 0.07
        insurance_rate = 0.1

        (
            result_total_interest,
            result_provision,
            result_insurance,
        ) = get_adjusted_total_interest_rate(
            max_fee=max_fee, provision_fee=provision_fee, insurance_premium_rate=insurance_rate
        )

        assert result_total_interest == 0
        assert result_provision == 0
        assert result_insurance == 0.06

    def test_adjusted_total_interest_rate_case_equal(self):
        max_fee = 0.06
        provision_fee = 0.06
        insurance_rate = 0

        (
            result_total_interest,
            result_provision,
            result_insurance,
        ) = get_adjusted_total_interest_rate(
            max_fee=max_fee, provision_fee=provision_fee, insurance_premium_rate=insurance_rate
        )

        assert result_total_interest == 0
        assert result_provision == 0.06
        assert result_insurance == 0

        provision_fee = 0
        insurance_rate = 0.06

        (
            result_total_interest,
            result_provision,
            result_insurance,
        ) = get_adjusted_total_interest_rate(
            max_fee=max_fee, provision_fee=provision_fee, insurance_premium_rate=insurance_rate
        )

        assert result_total_interest == 0
        assert result_provision == 0
        assert result_insurance == 0.06

    def test_get_global_cap_for_tenure_threshold(self):
        parameters = {
            'default': 0.2,
            'tenure_thresholds': {
                "1": 0.2,
                "2": 0.2,
                "3": 0.2,
                "4": 0.2,
                "5": 0.2,
                "6": 0.266,
                "7": 0.266,
                "8": 0.266,
                "9": 0.266,
                "10": 0.4,
                "11": 0.4,
                "12": 0.4,
            }
        }
        self.global_cap_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.GLOBAL_CAP_PERCENTAGE,
            is_active=True,
            parameters=parameters,
        )
        global_fee = get_global_cap_for_tenure_threshold(4)
        self.assertEqual(global_fee, 0.002)
