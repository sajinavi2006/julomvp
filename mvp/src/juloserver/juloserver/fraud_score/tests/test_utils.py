from django.test import TestCase

from juloserver.fraud_score.utils import check_application_experiment_monnai_eligibility


class TestCheckApplicationMonnaiInsightEligibility(TestCase):
    def test_found_substring_in_range_test_group(self):
        test_group = ['00-01']

        result = check_application_experiment_monnai_eligibility(2000000100, test_group)
        self.assertTrue(result)
        result = check_application_experiment_monnai_eligibility(2000000100, test_group)
        self.assertTrue(result)

        # Multiple test_group value check
        test_group = ['00-01', '11-22', '44-99']
        result = check_application_experiment_monnai_eligibility(2000000100, test_group)
        self.assertTrue(result)
        result = check_application_experiment_monnai_eligibility(2000001500, test_group)
        self.assertTrue(result)
        result = check_application_experiment_monnai_eligibility(2000009990, test_group)
        self.assertTrue(result)

    def test_not_found_substring_in_range_test_group(self):
        test_group = ['00-01']

        result = check_application_experiment_monnai_eligibility(2000001100, test_group)
        self.assertFalse(result)

        # Multiple test_group value check
        test_group = ['00-01', '11-22', '44-99']
        result = check_application_experiment_monnai_eligibility(2000000200, test_group)
        self.assertFalse(result)
        result = check_application_experiment_monnai_eligibility(2000001000, test_group)
        self.assertFalse(result)
        result = check_application_experiment_monnai_eligibility(2000004344, test_group)
        self.assertFalse(result)

    def test_no_test_group_raise_exception(self):
        test_group = []
        with self.assertRaises(Exception):
            check_application_experiment_monnai_eligibility(2000001100, test_group)
