from datetime import datetime
from unittest import mock

from django.test import TestCase
from requests import (
    ConnectionError,
    HTTPError,
)
from juloserver.julo.exceptions import JuloException
from juloserver.sales_ops_pds.services.download_data_services import (
    AIRudderPDSDownloadService,
    AIRudderPDSDownloadManager,
)

SUB_APP = 'juloserver.sales_ops_pds'


class TestAIRudderDownloadTask(TestCase):
    def setUp(self):
        self.call_list = [
            {
                "talkDuration": 0,
                "waitingDuration": 0,
                "talkedTime": 0,
                "holdDuration": 0,
                "nthCall": 2,
                "biztype": "group_sales_ops",
                "hangupReason": 18,
                "taskId": "abcxyz",
                "taskName": "test",
                "callid": "605d7972b2b24c27bb788ff37965da48",
                "phoneNumber": "+628997483000",
                "mainNumber": "+628997483000",
                "calltime": "2024-12-02T06:21:36Z",
                "ringtime": "",
                "answertime": "",
                "talktime": "",
                "endtime": "2024-12-02T06:21:50Z",
                "agentName": "",
                "adminAct": [],
                "transferReason": "",
                "reclink": "",
                "customerName": "",
                "callResultType": "NoAnwsered",
                "callType": "auto",
                "customerInfo": {
                    "account_id": "1000001",
                    "customer_id": "1000000001",
                    "application_id": "2000000001",
                    "available_limit": "1500000",
                    "customer_type": "repeat_os",
                    "data_date": "2024-11-21",
                    "fullname": "Prod Only",
                    "gender": "Pria",
                    "is_12M_user": "non_12M_user",
                    "is_high_value_user": "average_value_user",
                    "latest_active_dates": "2023-12-11",
                    "latest_loan_fund_transfer_ts": "2019-05-15T02:15:09.116700Z",
                    "m_score": "1",
                    "r_score": "1",
                    "set_limit": "1200000",
                    "set_limit": "1200000",
                    "biaya_admin_baru": "0.0",
                    "biaya_admin_sebelumnya": "0.01",
                    "bunga_cicilan_baru": "0.02",
                    "bunga_cicilan_sebelumnya": "0.03",
                    "cicilan_per_bulan_baru": "2.72jt",
                    "cicilan_per_bulan_sebelumnya": "3.44jt",
                    "partition_date": "2024-12-10",
                    "customer_segment": "churned_customer",
                    "schema_amount": "18jt",
                    "schema_loan_duration": "9",
                    "saving_overall_after_np": "7.74jt"
                },
                "customizeResults": [
                    {
                        "title": "Level1",
                        "groupName": "",
                        "value": "Not_Connected"
                    },
                    {
                        "title": "Level2",
                        "groupName": "",
                        "value": "mail_box"
                    },
                    {
                        "title": "Level3",
                        "groupName": "",
                        "value": ""
                    }
                ]
            },
            {
                "talkDuration": 0,
                "waitingDuration": 0,
                "talkedTime": 0,
                "holdDuration": 0,
                "nthCall": 2,
                "biztype": "group_sales_ops",
                "hangupReason": 18,
                "taskId": "abcxyz",
                "taskName": "test",
                "callid": "605d7972b2b24c27bb788ff37965da50",
                "phoneNumber": "+628997483001",
                "mainNumber": "+628997483001",
                "calltime": "2024-12-02T06:21:36Z",
                "ringtime": "",
                "answertime": "",
                "talktime": "",
                "endtime": "2024-12-02T06:21:50Z",
                "agentName": "",
                "adminAct": [],
                "transferReason": "",
                "reclink": "",
                "customerName": "",
                "callResultType": "NoAnwsered",
                "callType": "auto",
                "customerInfo": {
                    "account_id": "1000002",
                    "customer_id": "1000000002",
                    "application_id": "2000000002",
                    "available_limit": "1500000",
                    "customer_type": "repeat_os",
                    "data_date": "2024-11-21",
                    "fullname": "Prod Only",
                    "gender": "Pria",
                    "is_12M_user": "non_12M_user",
                    "is_high_value_user": "average_value_user",
                    "latest_active_dates": "2023-12-11",
                    "latest_loan_fund_transfer_ts": "2019-05-15T02:15:09.116700Z",
                    "m_score": "1",
                    "r_score": "1",
                    "set_limit": "1200000",
                    "set_limit": "1200000",
                    "biaya_admin_baru": "0.0",
                    "biaya_admin_sebelumnya": "0.01",
                    "bunga_cicilan_baru": "0.02",
                    "bunga_cicilan_sebelumnya": "0.03",
                    "cicilan_per_bulan_baru": "2.72jt",
                    "cicilan_per_bulan_sebelumnya": "3.44jt",
                    "partition_date": "2024-12-10",
                    "customer_segment": "churned_customer",
                    "schema_amount": "18jt",
                    "schema_loan_duration": "9",
                    "saving_overall_after_np": "7.74jt"
                },
                "customizeResults": [
                    {
                        "title": "Level 1",
                        "groupName": "",
                        "value": "Not_Connected"
                    },
                    {
                        "title": "Level 2",
                        "groupName": "",
                        "value": "mail_box"
                    },
                    {
                        "title": "Level 3",
                        "groupName": "",
                        "value": ""
                    }
                ]
            }
        ]

    @mock.patch.object(AIRudderPDSDownloadService, "get_airudder_client")
    def test_get_total_call_result_success(self, mock_get_airudder_client):
        airudder_download_service = AIRudderPDSDownloadService(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )
        mock_client = mock.MagicMock()
        mock_client.query_task_detail.return_value = {
            "body": {
                "total": 2,
                "list": self.call_list
            }
        }
        mock_get_airudder_client.return_value = mock_client
        total = airudder_download_service.get_total()

        self.assertEqual(total, 2)
        mock_client.query_task_detail.assert_called_once_with(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59),
            limit=1,
            offset=0
        )

    @mock.patch.object(AIRudderPDSDownloadService, "get_airudder_client")
    def test_get_call_list_success(self, mock_get_airudder_client):
        airudder_download_service = AIRudderPDSDownloadService(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )
        mock_client = mock.MagicMock()
        mock_client.query_task_detail.return_value = {
            "body": {
                "total": 2,
                "list": self.call_list
            }
        }
        mock_get_airudder_client.return_value = mock_client
        call_list = airudder_download_service.get_call_list(offset=0, limit=2)

        self.assertEqual(call_list, self.call_list)

        mock_client.query_task_detail.assert_called_once_with(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59),
            limit=2,
            offset=0,
            need_customer_info=True
        )

    @mock.patch.object(AIRudderPDSDownloadService, "get_airudder_client")
    def test_get_total_call_result_no_response(self, mock_get_airudder_client):
        airudder_download_service = AIRudderPDSDownloadService(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )
        mock_client = mock.MagicMock()
        mock_client.query_task_detail.return_value = {}

        with self.assertRaises(JuloException):
            mock_get_airudder_client.return_value = mock_client
            airudder_download_service.get_total()

    @mock.patch.object(AIRudderPDSDownloadService, "get_airudder_client")
    def test_get_call_list_no_response(self, mock_get_airudder_client):
        airudder_download_service = AIRudderPDSDownloadService(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )
        mock_client = mock.MagicMock()
        mock_client.query_task_detail.return_value = {}

        with self.assertRaises(JuloException):
            mock_get_airudder_client.return_value = mock_client
            airudder_download_service.get_call_list(offset=0, limit=2)

    @mock.patch.object(AIRudderPDSDownloadService, "get_airudder_client")
    def test_get_total_call_result_no_total(self, mock_get_airudder_client):
        airudder_download_service = AIRudderPDSDownloadService(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )
        mock_client = mock.MagicMock()
        mock_client.query_task_detail.return_value = {
            "body": {}
        }

        with self.assertRaises(JuloException):
            mock_get_airudder_client.return_value = mock_client
            airudder_download_service.get_total()

    @mock.patch.object(AIRudderPDSDownloadService, "get_airudder_client")
    def test_get_total_call_list_no_call_list(self, mock_get_airudder_client):
        airudder_download_service = AIRudderPDSDownloadService(
            task_id="abcxyz",
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )
        mock_client = mock.MagicMock()
        mock_client.query_task_detail.return_value = {
            "body": {}
        }

        with self.assertRaises(JuloException):
            mock_get_airudder_client.return_value = mock_client
            airudder_download_service.get_call_list(offset=0, limit=2)


class TestAIRudderDownloadTaskManager(TestCase):
    def setUp(self):
        self.total = 2
        self.call_list = [
            {
                "talkDuration": 0,
                "waitingDuration": 0,
                "talkedTime": 0,
                "holdDuration": 0,
                "nthCall": 2,
                "biztype": "group_sales_ops",
                "hangupReason": 18,
                "taskId": "abcxyz",
                "taskName": "test",
                "callid": "605d7972b2b24c27bb788ff37965da48",
                "phoneNumber": "+628997483000",
                "mainNumber": "+628997483000",
                "calltime": "2024-12-02T06:21:36Z",
                "ringtime": "",
                "answertime": "",
                "talktime": "",
                "endtime": "2024-12-02T06:21:50Z",
                "agentName": "",
                "reclink": "",
                "customerName": "",
                "callResultType": "NoAnwsered",
                "callType": "auto",
                "customerInfo": {
                    "account_id": "2747036",
                    "customer_id": "1014151639"
                },
                "customizeResults": [
                    {
                        "title": "Level1",
                        "groupName": "",
                        "value": "NotConnected"
                    },
                    {
                        "title": "Level2",
                        "groupName": "",
                        "value": "mail_box"
                    },
                    {
                        "title": "Level3",
                        "groupName": "",
                        "value": ""
                    }
                ]
            },
            {
                "talkDuration": 0,
                "waitingDuration": 0,
                "talkedTime": 0,
                "holdDuration": 0,
                "nthCall": 2,
                "biztype": "group_sales_ops",
                "hangupReason": 18,
                "taskId": "abcxyz",
                "taskName": "test",
                "callid": "605d7972b2b24c27bb788ff37965da50",
                "phoneNumber": "+628997483001",
                "mainNumber": "+628997483001",
                "calltime": "2024-12-02T06:21:36Z",
                "ringtime": "",
                "answertime": "",
                "talktime": "",
                "endtime": "2024-12-02T06:21:50Z",
                "agentName": "",
                "reclink": "",
                "customerName": "",
                "callResultType": "NoAnwsered",
                "callType": "auto",
                "customerInfo": {
                    "account_id": "2747036",
                    "customer_id": "1014151639"
                },
                "customizeResults": [
                    {
                        "title": "Level1",
                        "groupName": "",
                        "value": "NotConnected"
                    },
                    {
                        "title": "Level2",
                        "groupName": "",
                        "value": "mail_box"
                    },
                    {
                        "title": "Level3",
                        "groupName": "",
                        "value": ""
                    }
                ]
            }
        ]

    def test_get_total_call_result(self):
        mock_airudder_download = mock.MagicMock()
        mock_airudder_download.task_id = "abcxyz"
        mock_airudder_download.start_time = datetime(2024, 12, 4, 8, 0, 0)
        mock_airudder_download.end_time = datetime(2024, 12, 4, 8, 59, 59)
        mock_airudder_download.get_total.return_value = self.total

        manager = AIRudderPDSDownloadManager(mock_airudder_download)
        total = manager.get_total()
        self.assertEqual(total, self.total)

    def test_get_call_list(self):
        mock_airudder_download = mock.MagicMock()
        mock_airudder_download.task_id = "abcxyz"
        mock_airudder_download.start_time = datetime(2024, 12, 4, 8, 0, 0)
        mock_airudder_download.end_time = datetime(2024, 12, 4, 8, 59, 59)
        mock_airudder_download.get_call_list.return_value = self.call_list

        manager = AIRudderPDSDownloadManager(mock_airudder_download)
        call_list = manager.get_call_list(offset=0, limit=2)
        self.assertEqual(call_list, self.call_list)

    def test_get_call_list_connection_error(self):
        mock_airudder_download = mock.MagicMock()
        mock_airudder_download.get_call_list.side_effect = \
            ConnectionError("Connection Error")

        manager = AIRudderPDSDownloadManager(mock_airudder_download)

        with self.assertRaises(AIRudderPDSDownloadManager.NeedRetryException):
            manager.get_call_list(offset=0, limit=2)

    def test_get_call_list_no_retry_on_400(self):
        mock_airudder_download = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        mock_airudder_download.get_call_list.side_effect = HTTPError(
            "Connection Error", response=mock_response
        )

        manager = AIRudderPDSDownloadManager(mock_airudder_download)
        with self.assertRaises(HTTPError):
            manager.get_call_list(offset=0, limit=2)

    def test_get_call_list_retry_no_resp_http_error(self):
        mock_airudder_download = mock.MagicMock()
        mock_airudder_download.get_call_list.side_effect = HTTPError("Connection Error")

        manager = AIRudderPDSDownloadManager(mock_airudder_download)
        with self.assertRaises(AIRudderPDSDownloadManager.NeedRetryException):
            manager.get_call_list(offset=0, limit=2)

    def test_get_call_list_retry_on_429(self):
        mock_airudder_download = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        mock_airudder_download.get_call_list.side_effect = HTTPError(
            "Connection Error", response=mock_response,
        )

        manager = AIRudderPDSDownloadManager(mock_airudder_download)
        with self.assertRaises(AIRudderPDSDownloadManager.NeedRetryException):
            manager.get_call_list(offset=0, limit=2)
