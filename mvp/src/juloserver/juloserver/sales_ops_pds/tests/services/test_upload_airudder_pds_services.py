from datetime import datetime
from unittest import mock

from django.utils import timezone
from django.test import TestCase
from requests import (
    ConnectionError,
    HTTPError,
)
from django.conf import settings

from juloserver.julo.exceptions import JuloException
from juloserver.minisquad.constants import AiRudder
from juloserver.sales_ops_pds.services.upload_data_services import (
    AIRudderPDSUploadService,
    AIRudderPDSUploadManager,
)


class TestAIRudderUploadTask(TestCase):
    def setUp(self):
        self.strategy_config = {
            "groupName": "SalesOpsA_RepeatOS",
            "start_time": "8:00",
            "end_time": "18:00",
            "acwTime": "40",
            "ringLimit": "20",
            "rest_times": [["11:00", "12:00"]],
            "autoSlotFactor": "0",
            "dialingMode": "1",
            "maxLostRate": "12",
            "repeatTimes": "2",
            "bulkCallInterval": "300",
            "dialingOrder": ["PhoneNumber"],
            "voiceCheck": "1",
            "voiceCheckDuration": "2500",
            "voiceHandle": "1"
        }
        self.customer_list = [{
            "PhoneNumber": "+6281279377937",
            "gender": "Pria",
            "fullname": "Tomato Capuchino",
            "available_limit": "5000000",
            "set_limit": "4000000",
            "customer_type": "repeat_os",
            "application_history_x190_cdate": "2024-11-11Z12:23:34",
            "latest_loan_fund_transfer_ts": "2024-11-11Z13:34:45",
            "is_12m_user": "non_12M_user",
            "is_high_value_user": "average_value_user",
            "kode_voucher": "PROMOCODE1234",
            "scheme": "abc",
            "biaya_admin_sebelumnya": "0.0007",
            "biaya_admin_baru": "0.09",
            "r_score": "1",
            "m_score": "1",
            "latest_active_dates": "2024-11-10",
            "customer_id": "1000000001",
            "application_id": "2000000001",
            "account_id": "100001",
            "data_date": "2024-11-11",
            "partition_date": "2024-11-11",
            "customer_segment": "segment_a",
            "schema_amount": "1000000",
            "schema_loan_duration": "2",
            "cicilan_per_bulan_sebelumnya": "100",
            "cicilan_per_bulan_baru": "100",
            "saving_overall_after_np": "1"
        }]

    def test_validate_strategy_config(self):
        now = timezone.localtime(datetime(2024, 11, 11, 6, 23, 34))
        with mock.patch.object(timezone, "now", return_value=now):
            airudder_upload_service = AIRudderPDSUploadService(
                bucket_code="sales_ops_a",
                customer_type="repeat_os",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                batch_number=1,
            )

        strategy_config = airudder_upload_service.strategy_config
        expected_strategy_config = {
            "groupName": "SalesOpsA_RepeatOS",
            "start_time": now.replace(hour=8, minute=0, second=0),
            "end_time": now.replace(hour=18, minute=0, second=0),
            "restTimes": [{"start": "11:00:00", "end": "12:00:00"}],
            "acwTime": 40,
            "ringLimit": 20,
            "dialingMode": 1,
            "dialingOrder": ["PhoneNumber"],
            "maxLostRate": 12,
            "repeatTimes": 2,
            "slotFactor": 2.5,
            "autoSlotFactor": 0,
            "bulkCallInterval": 300,
            "voiceCheck": 1,
            "voiceCheckDuration": 2500,
            "voiceHandle": 1
        }
        self.assertEqual(strategy_config, expected_strategy_config)

    def test_validate_customer_list(self):
        customer_list = [{
            "PhoneNumber": "+6281279377937",
            "gender": "Pria",
            "fullname": "Tomato Capuchino",
            "available_limit": "5_000_000",
            "set_limit": "4_000_000",
            "customer_type": "repeat_os",
            "application_history_x190_cdate": "2024-11-11T12:23:34",
            "latest_loan_fund_transfer_ts": "2024-11-10T13:34:45",
        }, {
            "PhoneNumber": "+6281279377937",
            "gender": None,
            "fullname": "Potato Capuchino",
            "available_limit": 6_000_000,
            "set_limit": 5_000_000,
            "customer_type": "repeat_os",
            "application_history_x190_cdate": datetime(2024, 11, 11, 12, 23, 34),
            "latest_loan_fund_transfer_ts": datetime(2024, 11, 10, 13, 34, 45),
        }]

        now = timezone.localtime(datetime(2024, 11, 11, 6, 23, 34))
        with mock.patch.object(timezone, "now", return_value=now):
            airudder_upload_service = AIRudderPDSUploadService(
                bucket_code="sales_ops_a",
                customer_type="repeat_os",
                strategy_config=self.strategy_config,
                customer_list=customer_list,
                batch_number=1,
            )

        customer_list = airudder_upload_service.customer_list
        expected_customer_list = [{
            "PhoneNumber": "+6281279377937",
            "gender": "Pria",
            "fullname": "Tomato Capuchino",
            "available_limit": "5_000_000",
            "set_limit": "4_000_000",
            "customer_type": "repeat_os",
            "application_history_x190_cdate": "2024-11-11T12:23:34",
            "latest_loan_fund_transfer_ts": "2024-11-10T13:34:45",
        }, {
            "PhoneNumber": "+6281279377937",
            "gender": "",
            "fullname": "Potato Capuchino",
            "available_limit": "6000000",
            "set_limit": "5000000",
            "customer_type": "repeat_os",
            "application_history_x190_cdate": "2024-11-11T12:23:34",
            "latest_loan_fund_transfer_ts": "2024-11-10T13:34:45",
        }]
        self.assertEqual(customer_list, expected_customer_list)

    def test_get_task_name(self):
        now = timezone.localtime(datetime(2024, 11, 11, 6, 23, 34))
        with mock.patch.object(timezone, "now", return_value=now):
            airudder_upload_service = AIRudderPDSUploadService(
                bucket_code="sales_ops_a",
                customer_type="repeat_os",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                batch_number=2,
            )
            task_name = airudder_upload_service.get_task_name()

        setting_env = settings.ENVIRONMENT.upper()
        expected_task_name = "{env}_{task_name}".format(
            env=setting_env,
            task_name="SalesOpsA_RepeatOs_20241111-0623_p2"
        )
        self.assertEqual(expected_task_name, task_name)

    @mock.patch.object(AIRudderPDSUploadService, "get_airudder_client")
    def test_create_task_success(self, mock_get_airudder_client):
        now = timezone.localtime(datetime(2024, 11, 11, 6, 23, 34))
        with mock.patch.object(timezone, "now", return_value=now):
            airudder_upload_service = AIRudderPDSUploadService(
                bucket_code="sales_ops_a",
                customer_type="repeat_os",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                batch_number=1,
            )
            mock_client = mock.MagicMock()
            mock_client.create_task.return_value = {
                "body": {
                    "taskId": "airudder-task-id",
                    "errorContactList": []
                }
            }
            mock_get_airudder_client.return_value = mock_client
            task_id, error_contact_list = airudder_upload_service.create_task()

            self.assertEqual(task_id, "airudder-task-id")
            self.assertEqual(error_contact_list, [])
            mock_client.create_task.assert_called_once_with(
                task_name=mock.ANY,
                start_time=now.replace(hour=8, minute=0, second=0),
                end_time=now.replace(hour=18, minute=0, second=0),
                group_name=self.strategy_config["groupName"],
                list_contact_to_call=mock.ANY,
                call_back_url=mock.ANY,
                strategy_config=mock.ANY,
                partner_name=AiRudder.SALES_OPS
            )

    @mock.patch.object(AIRudderPDSUploadService, "get_airudder_client")
    def test_create_task_no_response(self, mock_get_airudder_client):
        now = timezone.localtime(datetime(2024, 11, 11, 6, 23, 34))
        with mock.patch.object(timezone, "now", return_value=now):
            airudder_upload_service = AIRudderPDSUploadService(
                bucket_code="sales_ops_a",
                customer_type="repeat_os",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                batch_number=1,
            )
            mock_client = mock.MagicMock()
            mock_client.create_task.return_value = {}

            with self.assertRaises(JuloException):
                mock_get_airudder_client.return_value = mock_client
                airudder_upload_service.create_task()

    @mock.patch.object(AIRudderPDSUploadService, "get_airudder_client")
    def test_create_task_no_task_id(self, mock_get_airudder_client):
        now = timezone.localtime(datetime(2024, 11, 11, 6, 23, 34))
        with mock.patch.object(timezone, "now", return_value=now):
            airudder_upload_service = AIRudderPDSUploadService(
                bucket_code="sales_ops_a",
                customer_type="repeat_os",
                strategy_config=self.strategy_config,
                customer_list=self.customer_list,
                batch_number=1,
            )
            mock_client = mock.MagicMock()
            mock_client.create_task.return_value = {
                "body": {}
            }

            with self.assertRaises(JuloException):
                mock_get_airudder_client.return_value = mock_client
                airudder_upload_service.create_task()


class TestAIRudderUploadTaskManager(TestCase):
    def test_create_pds_task(self):
        mock_airudder_upload = mock.MagicMock()
        mock_airudder_upload.bucket_code = "sales_ops_a"
        mock_airudder_upload.customer_type = "repeat_os"
        mock_airudder_upload.group_name = "SalesOpsA_RepeatOS"
        mock_airudder_upload.customer_list = [
            {
                "PhoneNumber": "+6281279377937",
                "gender": "Pria",
                "fullname": "Tomato Capuchino",
                "available_limit": "5000000",
                "set_limit": "4000000",
                "customer_type": "repeat_os",
                "application_history_x190_cdate": "2024-11-11Z12:23:34",
                "latest_loan_fund_transfer_ts": "2024-11-11Z13:34:45",
                "is_12M_user": "non_12M_user",
                "is_high_value_user": "average_value_user",
                "kode_voucher": "PROMOCODE1234",
                "scheme": "abc",
                "biaya_admin_sebelumnya": "0.0007",
                "biaya_admin_baru": "0.09",
                "r_score": "1",
                "m_score": "1",
                "latest_active_dates": "2024-11-10",
                "customer_id": "1000000001",
                "application_id": "2000000001",
                "account_id": "100001",
                "data_date": "2024-11-11",
                "partition_date": "2024-11-11",
                "customer_segment": "segment_a",
                "schema_amount": "1000000",
                "schema_loan_duration": "2",
                "cicilan_per_bulan_sebelumnya": "100",
                "cicilan_per_bulan_baru": "100",
                "saving_overall_after_np": "1"
            }
        ]
        mock_airudder_upload.create_task.return_value = "task-Id", []
        manager = AIRudderPDSUploadManager(mock_airudder_upload)
        task_id, error_customer_list = manager.create_task()
        self.assertEqual(task_id, "task-Id")
        self.assertEqual(error_customer_list, [])

    def test_create_pds_task_connection_error(self):
        mock_airudder_upload = mock.MagicMock()
        mock_airudder_upload.create_task.side_effect = ConnectionError("Connection Error")

        manager = AIRudderPDSUploadManager(mock_airudder_upload)

        with self.assertRaises(AIRudderPDSUploadManager.NeedRetryException):
            manager.create_task()

    def test_create_task_no_retry_on_400(self):
        mock_airudder_upload = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        mock_airudder_upload.create_task.side_effect = HTTPError(
            "Connection Error", response=mock_response,
        )

        manager = AIRudderPDSUploadManager(mock_airudder_upload)
        with self.assertRaises(HTTPError):
            manager.create_task()

    def test_create_task_retry_no_resp_http_error(self):
        mock_airudder_upload = mock.MagicMock()
        mock_airudder_upload.create_task.side_effect = HTTPError("Connection Error")

        manager = AIRudderPDSUploadManager(mock_airudder_upload)
        with self.assertRaises(AIRudderPDSUploadManager.NeedRetryException):
            manager.create_task()

    def test_create_task_retry_on_429(self):
        mock_airudder_upload = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        mock_airudder_upload.create_task.side_effect = HTTPError(
            "Connection Error", response=mock_response,
        )

        manager = AIRudderPDSUploadManager(mock_airudder_upload)
        with self.assertRaises(AIRudderPDSUploadManager.NeedRetryException):
            manager.create_task()
