import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase

from juloserver.minisquad.constants import RedisKey
from juloserver.minisquad.services2.airudder import (
    get_airudder_request_temp_data_from_cache,
    store_dynamic_airudder_config,
)


@mock.patch('juloserver.minisquad.services2.airudder.get_redis_client')
class TestGetAirudderRequestTempDataFromCache(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.valid_raw_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "14:00",
                "end_time": "20:00",
            },
            "customers": [
                {
                    "account_payment_id": "3212341",
                    "account_id": "123",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                    "nama_customer": "John Doe",
                }
            ],
        }

    def test_valid_data(self, mock_redis):
        mock_redis.return_value.get.return_value = json.dumps(self.valid_raw_data)

        result = get_airudder_request_temp_data_from_cache("the-redis-key")
        self.assertEqual("omnichannel_1234", result['bucket_name'])

    def test_not_found_data(self, mock_redis):
        mock_redis.return_value.get.return_value = None

        with self.assertRaises(ValueError):
            get_airudder_request_temp_data_from_cache("the-redis-key")


@mock.patch('juloserver.minisquad.services2.airudder.get_redis_client')
@mock.patch('juloserver.minisquad.services2.ai_rudder_pds.AiRudderPDSSettingManager')
class TestStoreDynamicAirudderConfig(TestCase):
    def test_call_recording_status_on(self, mock_setting_manager, mock_get_redis):
        strategy_config = {"callRecordingUpload": "on"}
        store_dynamic_airudder_config('bucket name', strategy_config)

        mock_setting_manager.return_value.enable_sending_recording.assert_called_once()
        mock_setting_manager.return_value.save_strategy_config.has_no_call()

        mock_get_redis.return_value.set_list.assert_called_once_with(
            RedisKey.DYNAMIC_AIRUDDER_CONFIG,
            'bucket name',
            expire_time=timedelta(hours=24),
        )

    def test_timeframe_status_on(self, mock_setting_manager, mock_get_redis):
        strategy_config = {"timeFrameStatus": "on"}
        store_dynamic_airudder_config('bucket name', strategy_config)

        mock_setting_manager.return_value.save_strategy_config.assert_called_once_with(
            strategy_config,
        )
        mock_setting_manager.return_value.enable_sending_recording.has_no_call()

        mock_get_redis.return_value.set_list.assert_called_once_with(
            RedisKey.DYNAMIC_AIRUDDER_CONFIG,
            'bucket name',
            expire_time=timedelta(hours=24),
        )
