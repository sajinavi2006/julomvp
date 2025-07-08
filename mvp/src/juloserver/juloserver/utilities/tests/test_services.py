from django.test.testcases import TestCase
from mock import patch

from juloserver.utilities.services import get_holdout_variables, HoldoutManager
from juloserver.julocore.cache_client import get_loc_mem_cache


class TestGetHoldoutVariables(TestCase):

    def test_10p_of_10r(self):
        variables = get_holdout_variables(percentage=10, total_request=10)
        self.assertEqual(variables['list_left'], [1,2,3,4,5,6,7,8,9])
        self.assertEqual(variables['list_right'], [10])
        self.assertEqual(variables['list_requests'], [1,2,3,4,5,6,7,8,9,10])
        self.assertEqual(variables['percentage_multiplier'], 0.1)
        self.assertEqual(variables['total_left'], 9)
        self.assertEqual(variables['total_right'], 1)
        self.assertEqual(variables['total_request'], 10)

    def test_13p_of_85r(self):
        variables = get_holdout_variables(percentage=13, total_request=85)
        # 13% * 85 = 11.05
        self.assertEqual(variables['list_left'], list(range(1, 75)))
        self.assertEqual(variables['list_right'], list(range(75, 86)))
        self.assertEqual(variables['list_requests'], list(range(1, 86)))
        self.assertEqual(variables['percentage_multiplier'], 0.13)
        self.assertEqual(variables['total_left'], 74)
        self.assertEqual(variables['total_right'], 11)
        self.assertEqual(variables['total_request'], 85)

    def test_10p_of_2r(self):
        variables = get_holdout_variables(percentage=10, total_request=2)
        # 10% * 2 = 0.2 -> 0
        self.assertEqual(variables['list_left'], [1, 2])
        self.assertEqual(variables['list_right'], [])
        self.assertEqual(variables['list_requests'], [1, 2])
        self.assertEqual(variables['percentage_multiplier'], 0.1)
        self.assertEqual(variables['total_left'], 2)
        self.assertEqual(variables['total_right'], 0)
        self.assertEqual(variables['total_request'], 2)

    def test_100p_of_2r(self):
        variables = get_holdout_variables(percentage=100, total_request=2)
        # 100% * 2 = 2
        self.assertEqual(variables['list_left'], [])
        self.assertEqual(variables['list_right'], [1, 2])
        self.assertEqual(variables['list_requests'], [1, 2])
        self.assertEqual(variables['percentage_multiplier'], 1.0)
        self.assertEqual(variables['total_left'], 0)
        self.assertEqual(variables['total_right'], 2)
        self.assertEqual(variables['total_request'], 2)

class TestGetHoldoutManagerVariables(TestCase):

    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    def test_10p_of_10r(self, mock_cache):
        with HoldoutManager(percentage=10, total_request=10, key="key-1") as holdout:
            variables = holdout.variables

        self.assertEqual(variables['list_left'], [1,2,3,4,5,6,7,8,9])
        self.assertEqual(variables['list_right'], [10])
        self.assertEqual(variables['list_requests'], [1,2,3,4,5,6,7,8,9,10])
        self.assertEqual(variables['percentage_multiplier'], 0.1)
        self.assertEqual(variables['total_left'], 9)
        self.assertEqual(variables['total_right'], 1)
        self.assertEqual(variables['total_request'], 10)

    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    def test_13p_of_85r(self, mock_cache):
        # 13% * 85 = 11.05
        with HoldoutManager(percentage=13, total_request=85, key="key-2") as holdout:
            variables = holdout.variables
            self.assertEqual(variables['list_left'], list(range(1, 75)))
            self.assertEqual(variables['list_right'], list(range(75, 86)))
            self.assertEqual(variables['list_requests'], list(range(1, 86)))
            self.assertEqual(variables['percentage_multiplier'], 0.13)
            self.assertEqual(variables['total_left'], 74)
            self.assertEqual(variables['total_right'], 11)
            self.assertEqual(variables['total_request'], 85)

    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    def test_10p_of_2r(self, mock_cache):
        # 10% * 2 = 0.2 -> 0
        with HoldoutManager(percentage=10, total_request=2, key="key-3") as holdout:
            variables = holdout.variables
            self.assertEqual(variables['list_left'], [1, 2])
            self.assertEqual(variables['list_right'], [])
            self.assertEqual(variables['list_requests'], [1, 2])
            self.assertEqual(variables['percentage_multiplier'], 0.1)
            self.assertEqual(variables['total_left'], 2)
            self.assertEqual(variables['total_right'], 0)
            self.assertEqual(variables['total_request'], 2)

    @patch.object(HoldoutManager, '_get_cache_driver', return_value=get_loc_mem_cache())
    def test_100p_of_2r(self, mock_cache):
        # 100% * 2 = 2
        with HoldoutManager(percentage=100, total_request=2, key="key-4") as holdout:
            variables = holdout.variables
            self.assertEqual(variables['list_left'], [])
            self.assertEqual(variables['list_right'], [1, 2])
            self.assertEqual(variables['list_requests'], [1, 2])
            self.assertEqual(variables['percentage_multiplier'], 1.0)
            self.assertEqual(variables['total_left'], 0)
            self.assertEqual(variables['total_right'], 2)
            self.assertEqual(variables['total_request'], 2)