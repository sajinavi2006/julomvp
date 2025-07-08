from collections import OrderedDict
from datetime import (
    datetime,
    time,
)
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from requests import (
    ConnectionError,
    HTTPError,
)

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.minisquad.constants import DialerTaskStatus
from juloserver.minisquad.models import (
    AIRudderPayloadTemp,
)
from juloserver.minisquad.services2.ai_rudder_pds import (
    AiRudderPDSManager,
    AiRudderPDSSender,
    AiRudderPDSSettingManager,
)
from juloserver.minisquad.tests.factories import DialerTaskFactory


class TestAiRudderPDSSettingManager(TestCase):
    def test_get_strategy_config_happy_path(self):
        feature_setting_parameters = {
            "bucket-1": {"bucket_name": "bucket-1"},
            "test-bucket": {"bucket_name": "test-bucket"},
        }
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=True,
            parameters=feature_setting_parameters,
        )
        manager = AiRudderPDSSettingManager("test-bucket")
        config = manager.get_strategy_config()
        self.assertEqual(config, feature_setting_parameters["test-bucket"])

    def test_get_strategy_config_no_feature_setting(self):
        feature_setting_parameters = {
            "bucket-1": {"bucket_name": "bucket-1"},
            "test-bucket": {"bucket_name": "test-bucket"},
        }
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=False,
            parameters=feature_setting_parameters,
        )
        manager = AiRudderPDSSettingManager("test-bucket")
        config = manager.get_strategy_config()
        self.assertIsNone(config)

    def test_is_sending_recording_enabled(self):
        feature_setting_parameters = {
            "buckets": ["bucket-1", "test-bucket"],
        }
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=True,
            parameters=feature_setting_parameters,
        )
        manager = AiRudderPDSSettingManager("test-bucket")
        self.assertTrue(manager.is_sending_recording_enabled())

    def test_is_sending_recording_enabled_no_feature_setting(self):
        feature_setting_parameters = {
            "buckets": ["bucket-1", "test-bucket"],
        }
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=False,
            parameters=feature_setting_parameters,
        )
        manager = AiRudderPDSSettingManager("test-bucket")
        self.assertFalse(manager.is_sending_recording_enabled())

    def test_remove_config_from_setting(self):
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=True,
            parameters={
                "buckets": ["bucket-1", "test-bucket"],
            },
        )
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=True,
            parameters={
                "bucket-1": {"bucket_name": "bucket-1"},
                "test-bucket": {"bucket_name": "test-bucket"},
            },
        )
        manager = AiRudderPDSSettingManager("test-bucket")
        manager.remove_config_from_setting()
        setting = FeatureSetting.objects.get(feature_name="ai_rudder_tasks_strategy_config")
        self.assertEqual(setting.parameters, {"bucket-1": {"bucket_name": "bucket-1"}})

        setting = FeatureSetting.objects.get(feature_name="sending_recording_configuration")
        self.assertEqual(setting.parameters, {"buckets": ["bucket-1"]})

    def test_remove_config_from_setting_no_bucket(self):
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=True,
            parameters={
                "buckets": ["bucket-1"],
            },
        )
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=True,
            parameters={
                "bucket-1": {"bucket_name": "bucket-1"},
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.remove_config_from_setting()

        setting = FeatureSetting.objects.get(feature_name="ai_rudder_tasks_strategy_config")
        self.assertEqual(setting.parameters, {"bucket-1": {"bucket_name": "bucket-1"}})

        setting = FeatureSetting.objects.get(feature_name="sending_recording_configuration")
        self.assertEqual(setting.parameters, {"buckets": ["bucket-1"]})

    def test_save_strategy_config(self):
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=True,
            parameters={
                "bucket-1": {"bucket_name": "bucket-1"},
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.save_strategy_config(
            {
                "groupName": "random-bucket",
                "start_time": time(13, 14),
                "end_time": time(15, 16),
                "rest_times": [[time(12, 0), time(13, 0)]],
            }
        )
        setting = FeatureSetting.objects.get(feature_name="ai_rudder_tasks_strategy_config")

        expected_config = {
            "groupName": "random-bucket",
            "start_time": "13:14",
            "end_time": "15:16",
            "rest_times": [["12:00", "13:00"]],
        }
        self.assertEqual(expected_config, setting.parameters.get("random-bucket"))

    def test_save_strategy_config_not_active(self):
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=False,
            parameters={
                "bucket-1": {"bucket_name": "bucket-1"},
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.save_strategy_config({"bucket_name": "random-bucket"})
        setting = FeatureSetting.objects.get(feature_name="ai_rudder_tasks_strategy_config")
        self.assertIsNone(setting.parameters.get("random-bucket"))

    def test_save_strategy_config_already_exists(self):
        FeatureSettingFactory(
            feature_name="ai_rudder_tasks_strategy_config",
            is_active=True,
            parameters={
                "bucket-1": {"bucket_name": "bucket-1"},
                "random-bucket": {"bucket_name": "current-random-bucket"},
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.save_strategy_config({"bucket_name": "random-bucket"})
        setting = FeatureSetting.objects.get(feature_name="ai_rudder_tasks_strategy_config")
        self.assertEqual(
            setting.parameters.get("random-bucket"),
            {"bucket_name": "current-random-bucket"},
        )

    def test_enable_sending_recording(self):
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=True,
            parameters={
                "buckets": ["bucket-1"],
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.enable_sending_recording()
        setting = FeatureSetting.objects.get(feature_name="sending_recording_configuration")
        self.assertEqual(setting.parameters.get("buckets"), ["bucket-1", "random-bucket"])

    def test_enable_sending_recording_not_active(self):
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=False,
            parameters={
                "buckets": ["bucket-1"],
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.enable_sending_recording()
        setting = FeatureSetting.objects.get(feature_name="sending_recording_configuration")
        self.assertEqual(setting.parameters.get("buckets"), ["bucket-1"])

    def test_enable_sending_recording_already_exists(self):
        FeatureSettingFactory(
            feature_name="sending_recording_configuration",
            is_active=True,
            parameters={
                "buckets": ["bucket-1", "random-bucket"],
            },
        )
        manager = AiRudderPDSSettingManager("random-bucket")
        manager.enable_sending_recording()
        setting = FeatureSetting.objects.get(feature_name="sending_recording_configuration")
        self.assertEqual(setting.parameters.get("buckets"), ["bucket-1", "random-bucket"])


class TestAiRudderPDSSender(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.strategy_config = {
            "groupName": "test-group",
            "start_time": "13:14",
            "end_time": "15:16",
        }
        cls.customer_list = [
            {
                "customer_id": "101",
                "account_payment_id": "201",
                "phonenumber": "08123456789",
                "nama_customer": "john doe",
                "due_amount": 100000,
            }
        ]
        cls.callback_url = "http://test-callback-url.com/callback/"

    def test_init_with_default(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )

        self.assertEqual("test-group", sender.group_name)

        # asert default strategy config
        strategy_config = sender.strategy_config
        expected_config = {
            "groupName": "test-group",
            "start_time": now.replace(hour=13, minute=14, second=0),
            "end_time": now.replace(hour=15, minute=16, second=0),
            "restTimes": [{"start": "12:00:00", "end": "13:00:00"}],
            "slotFactor": 2.5,
            "autoQA": "Y",
            "qaConfigId": 142,
            "qaLimitLength": 0,
            "qaLimitRate": 100,
        }
        self.assertEqual(dict(strategy_config), expected_config)

        # assert customer data
        expected_customer_data = [
            {
                "customer_id": "101",
                "account_payment_id": "201",
                "phonenumber": "08123456789",
                "nama_customer": "john doe",
                "due_amount": "100000",
            }
        ]
        self.assertEqual(sender.customer_list, expected_customer_data)

    def test_init_with_no_start_time(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        strategy_config = {
            "groupName": "test-group",
            "end_time": "15:16",
        }
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )

        self.assertEqual("test-group", sender.group_name)

        # asert default strategy config
        strategy_config = sender.strategy_config
        expected_config = {
            "groupName": "test-group",
            "start_time": now.replace(hour=12, minute=15, second=0),
            "end_time": now.replace(hour=15, minute=16, second=0),
            "restTimes": [{"start": "12:00:00", "end": "13:00:00"}],
            "slotFactor": 2.5,
            "autoQA": "Y",
            "qaConfigId": 142,
            "qaLimitLength": 0,
            "qaLimitRate": 100,
        }
        self.assertEqual(dict(strategy_config), expected_config)

    def test_init_with_start_time_already_pass(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        strategy_config = {
            "groupName": "test-group",
            "start_time": "08:00",
            "end_time": "15:16",
        }
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )

        self.assertEqual("test-group", sender.group_name)

        # asert default strategy config
        strategy_config = sender.strategy_config
        expected_config = {
            "groupName": "test-group",
            "start_time": now.replace(hour=12, minute=15, second=0),
            "end_time": now.replace(hour=15, minute=16, second=0),
            "restTimes": [{"start": "12:00:00", "end": "13:00:00"}],
            "slotFactor": 2.5,
            "autoQA": "Y",
            "qaConfigId": 142,
            "qaLimitLength": 0,
            "qaLimitRate": 100,
        }
        self.assertEqual(dict(strategy_config), expected_config)

    def test_init_with_end_time_already_pass(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        strategy_config = {
            "groupName": "test-group",
            "start_time": "08:00",
            "end_time": "12:12",
        }
        with mock.patch.object(timezone, "now", return_value=now):
            with self.assertRaises(ValueError):
                sender = AiRudderPDSSender(
                    bucket_name="test-bucket",
                    strategy_config=strategy_config,
                    customer_list=self.customer_list,
                    callback_url=self.callback_url,
                )

    def test_init_with_all_strategy_config(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        strategy_config_input = {
            "groupName": "GROUP_BUCKET_1",
            "start_time": "12:13",
            "end_time": "20:21",
            "autoQA": "N",
            "acwTime": "31",
            "ringLimit": "11",
            "rest_times": [["13:14", "14:15"]],
            "slotFactor": "3.5",
            "dialingMode": "1",
            "maxLostRate": "12",
            "qaLimitRate": "101",
            "repeatTimes": "3",
            "callInterval": "13",
            "dialingOrder": [
                "mobile_phone_2",
                "no_telp_pasangan",
                "no_telp_kerabat",
                "telp_perusahaan",
            ],
            "qaLimitLength": "14",
            "autoSlotFactor": "15",
            "bulkCallInterval": "301",
            "contactNumberInterval": "302",
            "timeFrameStatus": "on",
            "timeFrames": [
                {"repeatTimes": 4},
                {"repeatTimes": 5},
                {"repeatTimes": 3},
            ],
            "resultStrategies": "on",
            "resultStrategiesConfig": [
                {"oper": "==", "title": "Level2", "value": "WPC", "action": [1, 2], "dncDay": 1},
                {"oper": "==", "title": "Level2", "value": "ShortCall", "action": [1]},
            ],
            "callRecordingUpload": "on",
        }
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=strategy_config_input,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )

        self.assertEqual("GROUP_BUCKET_1", sender.group_name)

        # asert default strategy config
        strategy_config = sender.strategy_config
        expected_config = {
            "groupName": "GROUP_BUCKET_1",
            "start_time": now.replace(hour=12, minute=15, second=0),
            "end_time": now.replace(hour=20, minute=21, second=0),
            "restTimes": [{"start": "13:14:00", "end": "14:15:00"}],
            "autoQA": "N",
            "acwTime": 31,
            "ringLimit": 11,
            "slotFactor": 3.5,
            "dialingMode": 1,
            "maxLostRate": 12,
            "qaLimitLength": 14,
            "qaLimitRate": 101,
            "repeatTimes": 3,
            "callInterval": 13,
            "dialingOrder": [
                "mobile_phone_2",
                "no_telp_pasangan",
                "no_telp_kerabat",
                "telp_perusahaan",
            ],
            "autoSlotFactor": 15,
            "bulkCallInterval": 301,
            "contactNumberInterval": 302,
            "timeFrameStatus": "on",
            'timeFrames': [
                OrderedDict([('repeatTimes', 4), ('contactInfoSource', 'original_source')]),
                OrderedDict([('repeatTimes', 5), ('contactInfoSource', 'original_source')]),
                OrderedDict([('repeatTimes', 3), ('contactInfoSource', 'original_source')]),
            ],
            "resultStrategies": "on",
            "resultStrategiesConfig": [
                {"oper": "==", "title": "Level2", "value": "WPC", "action": [1, 2], "dncDay": 1},
                {"oper": "==", "title": "Level2", "value": "ShortCall", "action": [1]},
            ],
            "callRecordingUpload": "on",
        }
        self.assertEqual(dict(strategy_config), expected_config)

    def test_task_name(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
                batch_number=100,
                source="OMNICHANNEL",
            )
            task_name = sender.task_name()

        setting_env = settings.ENVIRONMENT.upper()
        expected_task_name = "{}__{}__{}__{}__{}".format(
            setting_env, "test-bucket", "100", "20210102-1213", "OMNICHANNEL"
        )
        self.assertEqual(expected_task_name, task_name)

    def test_send_task_success(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )
            mock_client = mock.MagicMock()
            mock_client.create_task.return_value = {"body": {"taskId": "airudder-task-id"}}

            sender.set_client(mock_client)
            task_id = sender.send_task()

        self.assertEqual("airudder-task-id", task_id)
        mock_client.create_task.assert_called_once_with(
            task_name=mock.ANY,
            start_time=now.replace(hour=13, minute=14, second=0),
            end_time=now.replace(hour=15, minute=16, second=0),
            group_name=self.strategy_config["groupName"],
            list_contact_to_call=mock.ANY,
            call_back_url="aHR0cDovL3Rlc3QtY2FsbGJhY2stdXJsLmNvbS9jYWxsYmFjay8=",
            strategy_config=mock.ANY,
        )

    def test_send_task_no_resp_body(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )
            mock_client = mock.MagicMock()
            mock_client.create_task.return_value = {}

            with self.assertRaises(Exception) as ctx:
                sender.set_client(mock_client)
                sender.send_task()

    def test_send_task_no_task_id(self):
        now = timezone.localtime(datetime(2021, 1, 2, 12, 13, 14))
        with mock.patch.object(timezone, "now", return_value=now):
            sender = AiRudderPDSSender(
                bucket_name="test-bucket",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                callback_url=self.callback_url,
            )
            mock_client = mock.MagicMock()
            mock_client.create_task.return_value = {
                "body": {},
            }

            with self.assertRaises(Exception) as ctx:
                sender.set_client(mock_client)
                sender.send_task()



@mock.patch('juloserver.minisquad.tasks2.write_log_for_report_async')
@mock.patch('juloserver.minisquad.services2.ai_rudder_pds.record_history_dialer_task_event')
class TestAiRudderPDSManager(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dialer_task = DialerTaskFactory()

    def test_create_task(
        self,
        mock_record_history_dialer_task_event,
        mock_write_log_for_report_async,
    ):
        account_payment = AccountPaymentFactory()
        mock_airudder_sender = mock.MagicMock()
        mock_airudder_sender.bucket_name = "test-bucket"
        mock_airudder_sender.account_payment_ids.return_value = [account_payment.id]
        mock_airudder_sender.customer_list = [
            {
                "customer_id": account_payment.account.customer_id,
                "account_id": account_payment.account_id,
                "account_payment_id": account_payment.id,
                "phonenumber": account_payment.account.customer.phone,
                "nama_customer": account_payment.account.customer.fullname,
                "nama_perusahaan": "",
                "posisi_karyawan": "PEGAWAI",
                "total_due_amount": "1234567",
            }
        ]
        mock_airudder_sender.send_task.return_value = "airudder-task-id"

        manager = AiRudderPDSManager(self.dialer_task, mock_airudder_sender)
        task_id = manager.create_task(batch_number=1, retry_number=2)

        self.assertEqual("airudder-task-id", task_id)

        # assert sent_to_dialer flow
        mock_write_log_for_report_async.delay.assert_called_once_with(
            bucket_name=mock_airudder_sender.bucket_name,
            task_id=task_id,
            account_payment_ids=[account_payment.id],
            dialer_task_id=self.dialer_task.id,
        )

        # Assert AiRudderPayloadTemp
        ai_rudder_payload_temp = AIRudderPayloadTemp.objects.filter(
            account_id=account_payment.account_id
        ).get()
        self.assertEqual(account_payment.account.customer_id, ai_rudder_payload_temp.customer_id)
        self.assertEqual(account_payment.account_id, ai_rudder_payload_temp.account_id)
        self.assertEqual(account_payment.id, ai_rudder_payload_temp.account_payment_id)
        self.assertEqual('test-bucket', ai_rudder_payload_temp.bucket_name)
        self.assertEqual("PEGAWAI", ai_rudder_payload_temp.posisi_karyawan)
        self.assertIsNone(ai_rudder_payload_temp.nama_perusahaan)
        self.assertEqual(1234567, ai_rudder_payload_temp.total_due_amount)

        # Assert Dialer task event
        mock_record_history_dialer_task_event.has_calls(
            [
                mock.call(
                    dict(
                        dialer_task=self.dialer_task,
                        status=DialerTaskStatus.UPLOADING_PER_BATCH.format(1, 2),
                    ),
                    is_update_status_for_dialer_task=False,
                ),
                mock.call(
                    dict(
                        dialer_task=self.dialer_task,
                        status=DialerTaskStatus.UPLOADED_PER_BATCH.format(1),
                    ),
                    is_update_status_for_dialer_task=False,
                ),
            ]
        )

    def test_create_task_connection_error(self, mock_record_history_dialer_task_event, *args):
        mock_airudder_sender = mock.MagicMock()
        mock_airudder_sender.send_task.side_effect = ConnectionError("Connection Error")

        manager = AiRudderPDSManager(self.dialer_task, mock_airudder_sender)

        with self.assertRaises(AiRudderPDSManager.NeedRetryException):
            manager.create_task(batch_number=1, retry_number=2)

        mock_record_history_dialer_task_event.has_calls(
            [
                mock.call(
                    dict(
                        dialer_task=self.dialer_task,
                        status=DialerTaskStatus.UPLOADING_PER_BATCH.format(1, 2),
                    ),
                    is_update_status_for_dialer_task=False,
                ),
                mock.call(
                    dict(
                        dialer_task=self.dialer_task,
                        status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                        error="Connection Error",
                    ),
                    error_message="Connection Error",
                    is_update_status_for_dialer_task=False,
                ),
            ]
        )

    def test_create_task_fail_max_retry(self, mock_record_history_dialer_task_event, *args):
        mock_airudder_sender = mock.MagicMock()
        mock_airudder_sender.send_task.side_effect = ConnectionError("Connection Error")

        manager = AiRudderPDSManager(self.dialer_task, mock_airudder_sender)

        with self.assertRaises(AiRudderPDSManager.NoNeedRetryException):
            manager.create_task(batch_number=1, retry_number=3)

        mock_record_history_dialer_task_event.has_calls(
            [
                mock.call(
                    dict(
                        dialer_task=self.dialer_task,
                        status=DialerTaskStatus.UPLOADING_PER_BATCH.format(1, 3),
                    ),
                    is_update_status_for_dialer_task=False,
                ),
                mock.call(
                    dict(
                        dialer_task=self.dialer_task,
                        status=DialerTaskStatus.FAILURE_BATCH.format(1),
                        error="Connection Error",
                    ),
                    error_message="Connection Error",
                ),
            ]
        )

    def test_create_task_no_retry_on_400(self, *args):
        mock_airudder_sender = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        mock_airudder_sender.send_task.side_effect = HTTPError(
            "Connection Error",
            response=mock_response,
        )

        manager = AiRudderPDSManager(self.dialer_task, mock_airudder_sender)
        with self.assertRaises(HTTPError):
            manager.create_task(batch_number=1, retry_number=2)

    def test_create_task_retry_no_resp_http_error(self, *args):
        mock_airudder_sender = mock.MagicMock()
        mock_airudder_sender.send_task.side_effect = HTTPError("Connection Error")

        manager = AiRudderPDSManager(self.dialer_task, mock_airudder_sender)
        with self.assertRaises(AiRudderPDSManager.NeedRetryException):
            manager.create_task(batch_number=1, retry_number=2)

    def test_create_task_retry_on_429(self, *args):
        mock_airudder_sender = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        mock_airudder_sender.send_task.side_effect = HTTPError(
            "Connection Error",
            response=mock_response,
        )

        manager = AiRudderPDSManager(self.dialer_task, mock_airudder_sender)
        with self.assertRaises(AiRudderPDSManager.NeedRetryException):
            manager.create_task(batch_number=1, retry_number=2)
