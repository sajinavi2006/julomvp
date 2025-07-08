from rest_framework.test import APITestCase

from juloserver.loyalty.constants import AdminSettingDailyRewardErrorMsg
from juloserver.loyalty.services.daily_checkin_related import is_validate_input_data


class TestAdminSetting(APITestCase):
    def setUp(self):
        self.clean_data = {
            "max_days_reach_bonus": 10,
        }

    def test_validate_admin_setting(self):
        self.clean_data['daily_reward'] = 'wrong_value'
        is_valid, error_message = is_validate_input_data(self.clean_data)
        self.assertFalse(is_valid)
        self.assertEqual(error_message, AdminSettingDailyRewardErrorMsg.INVALID_FORMAT)

        self.clean_data['daily_reward'] = {
            '31wdq': 10
        }
        is_valid, error_message = is_validate_input_data(self.clean_data)
        self.assertFalse(is_valid)
        self.assertEqual(error_message, AdminSettingDailyRewardErrorMsg.KEY_REQUIRED)

        self.clean_data['daily_reward'] = {
            'default': 10,
            '31wdq': 10
        }
        is_valid, error_message = is_validate_input_data(self.clean_data)
        self.assertFalse(is_valid)
        self.assertEqual(error_message, AdminSettingDailyRewardErrorMsg.INVALID_DATA_TYPE)

        self.clean_data['daily_reward'] = {
            'default': 10,
            '15': 10
        }
        is_valid, error_message = is_validate_input_data(self.clean_data)
        self.assertFalse(is_valid)
        self.assertEqual(error_message, AdminSettingDailyRewardErrorMsg.INVALID_DATA_CONDITION)

        self.clean_data['daily_reward'] = {
            'default': 10,
            '10': 'wrong value'
        }
        is_valid, error_message = is_validate_input_data(self.clean_data)
        self.assertFalse(is_valid)
        self.assertEqual(error_message, AdminSettingDailyRewardErrorMsg.INVALID_VALUE_TYPE)

        self.clean_data['daily_reward'] = {
            'default': 10,
            '10': 10
        }
        is_valid, error_message = is_validate_input_data(self.clean_data)
        self.assertTrue(is_valid)
        self.assertIsNone(error_message)
