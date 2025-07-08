from datetime import datetime

from django.test import TestCase
from unittest import mock
from requests import (
    HTTPError,
    ConnectionError,
    Timeout,
)

from juloserver.julo.exceptions import JuloException
from juloserver.sales_ops_pds.tests.factories import (
    AIRudderDialerTaskGroupFactory,
    AIRudderDialerTaskUploadFactory,
    AIRudderDialerTaskDownloadFactory,
)
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.sales_ops_pds.constants import SalesOpsPDSDataStoreType
from juloserver.sales_ops_pds.services.store_data_services import (
    StoreSalesOpsPDSUploadData,
    StoreSalesOpsPDSDownloadData,
    StoreSalesOpsPDSRecordingFile,
    SalesOpsPDSRecordingFileManager,
)
from juloserver.sales_ops_pds.models import AIRudderVendorRecordingDetail
from juloserver.sales_ops_pds.constants import FeatureNameConst

SUB_APP = 'juloserver.sales_ops_pds'


class TestStoreUploadDataServices(TestCase):
    def setUp(self):
        self.data = [
            {
                'id': 1,
                'customer_id': '1000000001',
                'application_id': '2000000001',
                'bucket_code': 'sales_ops_a',
                'customer_type': 'repeat_os'
            },
            {
                'id': 2,
                'customer_id': '1000000002',
                'application_id': '2000000002',
                'bucket_code': 'sales_ops_a',
                'customer_type': 'repeat_os'
            },
            {
                'id': 3,
                'customer_id': '1000000003',
                'application_id': '2000000003',
                'bucket_code': 'sales_ops_a',
                'customer_type': 'repeat_os'
            }
        ]
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=3
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group=self.dialer_task_group,
            total_uploaded=3,
            total_successful=3,
            total_failed=0,
            batch_number=1,
            task_id="abcxyz"
        )

    @mock.patch("django.utils.timezone.now")
    def test_get_upload_file_name(self, mock_now):
        mock_now.return_value = datetime(2024, 11, 9, 12, 23, 34)

        service = StoreSalesOpsPDSUploadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.UPLOAD_TO_AIRUDDER,
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        file_name = service.get_upload_file_name()
        expected_file_name = "SalesOpsA_RepeatOs_20241109-1223_p1.csv"
        self.assertEqual(file_name, expected_file_name)

    @mock.patch("django.utils.timezone.now")
    def test_get_remote_filepath(self, mock_now):
        mock_now.return_value = datetime(2024, 11, 9, 12, 23, 34)

        service = StoreSalesOpsPDSUploadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.UPLOAD_TO_AIRUDDER,
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        file_name = service.get_upload_file_name()
        remote_path = service.get_upload_remote_filepath(file_name)
        expected_remote_path = "{expected_remote_path}/{expected_file_name}".format(
            expected_remote_path="sales_ops_pds/upload/20241109",
            expected_file_name="SalesOpsA_RepeatOs_20241109-1223_p1.csv"
        )
        self.assertEqual(remote_path, expected_remote_path)

    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    @mock.patch("django.utils.timezone.now")
    def test_store_data_empty(self, mock_now, mock_upload_oss):
        mock_now.return_value = datetime(2024, 11, 9, 12, 23, 34)

        service = StoreSalesOpsPDSUploadData(
            data=[],
            store_type=SalesOpsPDSDataStoreType.UPLOAD_TO_AIRUDDER,
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        with self.assertRaises(JuloException) as e:
            service.store_data()
        mock_upload_oss.assert_not_called()

    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    @mock.patch("django.utils.timezone.now")
    def test_store_data_success(self, mock_now, mock_upload_oss):
        mock_now.return_value = datetime(2024, 11, 9, 12, 23, 34)

        service = StoreSalesOpsPDSUploadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.UPLOAD_TO_AIRUDDER,
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        service.store_data()
        mock_upload_oss.assert_called_once()

    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    @mock.patch("django.utils.timezone.now")
    def test_store_uploaded_data_oss_link(self, mock_now, mock_upload_oss):
        mock_now.return_value = datetime(2024, 11, 9, 12, 23, 34)

        service = StoreSalesOpsPDSUploadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.UPLOAD_TO_AIRUDDER,
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        service.store_uploaded_data()

        mock_upload_oss.assert_called_once()
        self.dialer_task_upload.refresh_from_db()
        self.assertEqual(
            self.dialer_task_upload.upload_file_url,
            "{prefix}/{file_name}".format(
                prefix="sales_ops_pds/upload/20241109",
                file_name="SalesOpsA_RepeatOs_20241109-1223_p1.csv"
            )
        )

    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    @mock.patch("django.utils.timezone.now")
    def test_store_failed_upload_data_task(self, mock_now, mock_upload_oss):
        mock_now.return_value = datetime(2024, 11, 9, 12, 23, 34)

        service = StoreSalesOpsPDSUploadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.UPLOAD_FAILED_TO_AIRUDDER,
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        service.store_failed_uploaded_data()

        mock_upload_oss.assert_called_once()
        self.dialer_task_upload.refresh_from_db()
        self.assertEqual(
            self.dialer_task_upload.result_file_url,
            "{prefix}/{file_name}".format(
                prefix="sales_ops_pds/upload_failed/20241109",
                file_name="SalesOpsA_RepeatOs_20241109-1223_p1.csv"
            )
        )


class TestStoreDownloadDataServices(TestCase):
    def setUp(self):
        self.data = [
            {
                "talkDuration": 25,
                "waitingDuration": 2,
                "talkedTime": 23,
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
                "talkremarks": "",
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
                        "title": "Level 1",
                        "groupName": "",
                        "value": "NotConnected"
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
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=3
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group=self.dialer_task_group,
            total_uploaded=3,
            total_successful=3,
            total_failed=0,
            batch_number=1,
            task_id="abcxyz"
        )
        self.dialer_task_download = AIRudderDialerTaskDownloadFactory(
            dialer_task_upload=self.dialer_task_upload,
            total_downloaded=1,
            time_range="2024-12-04T08:00:00Z_2024-12-04T08:59:59Z",
            offset=0,
            limit=10
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS_CALL_RESULT_FORMAT,
            parameters={
                "callid": "Call ID",
                "taskName": "Task Name",
                "endtime": "End Time",
                "calltime": "Dialing Time",
                "ringtime": "Ring Time",
                "talktime": "Talk Start Time",
                "taskName": "Task Name",
                "agentName": "Agent",
                "answertime": "Customer Pickup Time",
                "phoneNumber": "Customer Number",
                "talkedTime": "Talk Time",
                "customerName": "Contact Name",
                "holdDuration": "Hold Time",
                "talkDuration": "Billable Time",
                "callResultType": "Call Result",
                "waitingDuration": "Wait Time",
                "customerInfo": {
                    "account_id": "account_id",
                    "customer_id": "customer_id"
                },
                "customizeResults": True
            },
            is_active=False
        )

    def test_get_download_file_name(self):
        service = StoreSalesOpsPDSDownloadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=self.dialer_task_download.id
        )
        file_name = service.get_download_file_name()
        expected_file_name = "SalesOpsA_RepeatOs_2024-12-04T08:00:00Z_2024-12-04T08:59:59Z_o0_l10.csv"
        self.assertEqual(file_name, expected_file_name)

    @mock.patch("django.utils.timezone.now")
    def test_get_remote_filepath(self, mock_now):
        mock_now.return_value = datetime(2024, 12, 28, 12, 23, 34)

        service = StoreSalesOpsPDSDownloadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=self.dialer_task_download.id
        )
        file_name = service.get_download_file_name()
        remote_path = service.get_download_remote_filepath(file_name)
        expected_remote_path = "{expected_remote_path}/{expected_file_name}".format(
            expected_remote_path="sales_ops_pds/download/20241228",
            expected_file_name="SalesOpsA_RepeatOs_2024-12-04T08:00:00Z_2024-12-04T08:59:59Z_o0_l10.csv"
        )
        self.assertEqual(remote_path, expected_remote_path)

    def test_format_call_result_default_format(self):
        service = StoreSalesOpsPDSDownloadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=self.dialer_task_download.id
        )
        service.normalize_download_file()
        formatted_data = service.data[0]

        self.assertEqual(formatted_data["callid"], "605d7972b2b24c27bb788ff37965da48")
        self.assertEqual(formatted_data["taskName"], "test")
        self.assertEqual(formatted_data["phoneNumber"], "+628997483000")
        self.assertEqual(formatted_data["calltime"], "2024-12-02T06:21:36Z")
        self.assertEqual(formatted_data["ringtime"], "")
        self.assertEqual(formatted_data["talktime"], "")
        self.assertEqual(formatted_data["answertime"], "")
        self.assertEqual(formatted_data["endtime"], "2024-12-02T06:21:50Z")
        self.assertEqual(formatted_data["talkDuration"], 25)
        self.assertEqual(formatted_data["talkedTime"], 23)
        self.assertEqual(formatted_data["holdDuration"], 0)
        self.assertEqual(formatted_data["waitingDuration"], 2)

        self.assertEqual(formatted_data["account_id"], "1000001")
        self.assertEqual(formatted_data["customer_id"], "1000000001")

        self.assertEqual(formatted_data["level_1"], "NotConnected")
        self.assertEqual(formatted_data["level_2"], "mail_box")
        self.assertEqual(formatted_data["level_3"], "")

    def test_format_call_result_configured_format(self):
        self.feature_setting.update_safely(is_active=True)
        service = StoreSalesOpsPDSDownloadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=self.dialer_task_download.id
        )
        service.normalize_download_file()
        formatted_data = service.data[0]

        self.assertEqual(formatted_data["Call ID"], "605d7972b2b24c27bb788ff37965da48")
        self.assertEqual(formatted_data["Task Name"], "test")
        self.assertEqual(formatted_data["Customer Number"], "+628997483000")
        self.assertEqual(formatted_data["Dialing Time"], "2024-12-02T06:21:36Z")
        self.assertEqual(formatted_data["Ring Time"], "")
        self.assertEqual(formatted_data["Talk Start Time"], "")
        self.assertEqual(formatted_data["Customer Pickup Time"], "")
        self.assertEqual(formatted_data["End Time"], "2024-12-02T06:21:50Z")
        self.assertEqual(formatted_data["Billable Time"], 25)
        self.assertEqual(formatted_data["Talk Time"], 23)
        self.assertEqual(formatted_data["Hold Time"], 0)
        self.assertEqual(formatted_data["Wait Time"], 2)

        self.assertEqual(formatted_data["account_id"], "1000001")
        self.assertEqual(formatted_data["customer_id"], "1000000001")

        self.assertEqual(formatted_data["Level 1"], "NotConnected")
        self.assertEqual(formatted_data["Level 2"], "mail_box")
        self.assertEqual(formatted_data["Level 3"], "")

    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    def test_store_data_success(self, mock_upload_oss):
        service = StoreSalesOpsPDSDownloadData(
            data=self.data,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=self.dialer_task_download.id
        )
        service.store_data()
        mock_upload_oss.assert_called_once()


class TestStoreSalesOpsPDSRecordFileServices(TestCase):
    def setUp(self):
        self.agent = AgentFactory(
            user_extension="agent_sales_ops"
        )
        self.data = [
            {
                "bucket_code": "sales_ops_a",
                "talkDuration": 0,
                "hangupReason": 12,
                "taskId": "abcxyz",
                "taskName": "test",
                "callid": "605d7972b2b24c27bb788ff37965da48",
                "phoneNumber": "+628997483000",
                "calltime": "2024-12-04T12:25:36Z",
                "ringtime": "",
                "answertime": "",
                "talktime": "",
                "endtime": "2024-12-04T12:25:50Z",
                "agentName": "agent_sales_ops",
                "callResultType": "SuccUserHangup",
                "reclink": "https://pcc.airudder.com/download/20250110/65fc9b02daa44bef90c0fa5733614b8d/f986c1222c204c11abddd2c3feb84ba9.wav",
                "customerInfo": {
                    "account_id": 1000001,
                    "customer_id": 100000001,
                }
            },
            {
                "talkDuration": 0,
                "hangupReason": 13,
                "taskId": "abcxyz",
                "taskName": "test",
                "callid": "605d7972b2b24c27bb788ff37965da50",
                "phoneNumber": "+628997483001",
                "calltime": "2024-12-04T12:25:36Z",
                "ringtime": "",
                "answertime": "",
                "talktime": "",
                "endtime": "",
                "agentName": "agent_sales_ops",
                "callResultType": "SuccAgentHangup",
                "reclink": "https://pcc.airudder.com/download/20250110/65fc9b02daa44bef90c0fa5733614b8d/a8891ae08dff4752aeac7383bc9d98db.wav",
                "customerInfo": {
                    "account_id": 1000002,
                    "customer_id": 100000002,
                }
            }
        ]
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=3
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group=self.dialer_task_group,
            total_uploaded=3,
            total_successful=3,
            total_failed=0,
            batch_number=1,
            task_id="abcxyz"
        )

    @mock.patch("juloserver.sales_ops_pds.tasks.process_recording_file_task.delay")
    def test_retrieve_call_result_recordings(self, mock_process_recording_file_task):
        service = StoreSalesOpsPDSRecordingFile()
        dialer_task_upload_id = 123
        service.retrieve_call_result_recordings(self.data, dialer_task_upload_id)

        self.assertEqual(mock_process_recording_file_task.call_count, 2)

    def test_fetch_recording_file(self):
        service = StoreSalesOpsPDSRecordingFile()
        local_filepath = service.fetch_recording_file(reclink=self.data[0]['reclink'])
        self.assertEqual(local_filepath, "media/sales_ops_pds/f986c1222c204c11abddd2c3feb84ba9.wav")

    @mock.patch("django.utils.timezone.now")
    def test_get_upload_remote_filepath(self, mock_now):
        mock_now.return_value = datetime(2025, 1, 13, 12, 23, 34)
        local_filepath = "media/605d7972b2b24c27bb788ff37965da48-f986c1222c204c11abddd2c3feb84ba9.wav"
        service = StoreSalesOpsPDSRecordingFile()
        remote_path = service.get_upload_remote_filepath(
            local_filepath=local_filepath,
        )
        expected_remote_path = "{expected_remote_path}/{expected_file_name}".format(
            expected_remote_path="sales_ops_pds/recording_file/20250113",
            expected_file_name="605d7972b2b24c27bb788ff37965da48-f986c1222c204c11abddd2c3feb84ba9.wav",
        )
        self.assertEqual(remote_path, expected_remote_path)

    @mock.patch("django.utils.timezone.now")
    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    def test_store_data_success(self, mock_upload_oss, mock_now):
        mock_now.return_value = datetime(2025, 1, 13, 12, 23, 34)
        service = StoreSalesOpsPDSRecordingFile()
        local_filepath = service.fetch_recording_file(reclink=self.data[0]['reclink'])
        service.store_and_upload_recording_file(
            call_result=self.data[0],
            local_filepath=local_filepath,
            dialer_task_upload_id=self.dialer_task_upload.pk,
        )
        mock_upload_oss.assert_called_once()
        airudder_vendor_recording_detail = AIRudderVendorRecordingDetail.objects.get(
            call_id=self.data[0]["callid"],
            dialer_task_upload_id=self.dialer_task_upload.pk,
        )
        expected_remote_path = "{expected_remote_path}/{expected_file_name}".format(
            expected_remote_path="sales_ops_pds/recording_file/20250113",
            expected_file_name="f986c1222c204c11abddd2c3feb84ba9.wav",
        )

        self.assertIsNotNone(airudder_vendor_recording_detail)
        self.assertEqual(airudder_vendor_recording_detail.recording_url, expected_remote_path)


class TestSalesOpsPDSRecordingFileManager(TestCase):
    def setUp(self):
        self.mock_recording_file_service = mock.MagicMock()
        self.manager = SalesOpsPDSRecordingFileManager(self.mock_recording_file_service)
        self.reclink = "https://pcc.airudder.com/download/20250110/65fc9b02daa44bef90c0fa5733614b8d/a8891ae08dff4752aeac7383bc9d98db.wav"

    def test_fetch_recording_file_success(self):
        self.mock_recording_file_service.fetch_recording_file.return_value = "media/sales_ops_pds/a8891ae08dff4752aeac7383bc9d98db.wav"
        local_filepath = self.manager.fetch_recording_file(self.reclink)
        self.assertEqual(local_filepath, "media/sales_ops_pds/a8891ae08dff4752aeac7383bc9d98db.wav")

    def test_fetch_recording_file_connection_error(self):
        self.mock_recording_file_service.fetch_recording_file.side_effect = ConnectionError("Connection Error")
        with self.assertRaises(SalesOpsPDSRecordingFileManager.NeedRetryException):
            self.manager.fetch_recording_file(self.reclink)

    def test_fetch_recording_file_timeout_error(self):
        self.mock_recording_file_service.fetch_recording_file.side_effect = Timeout("Timeout Error")
        with self.assertRaises(SalesOpsPDSRecordingFileManager.NeedRetryException):
            self.manager.fetch_recording_file(self.reclink)

    def test_fetch_recording_file_http_error_no_response(self):
        self.mock_recording_file_service.fetch_recording_file.side_effect = HTTPError("HTTP Error")
        with self.assertRaises(SalesOpsPDSRecordingFileManager.NeedRetryException):
            self.manager.fetch_recording_file(self.reclink)

    def test_fetch_recording_file_http_error_429(self):
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        self.mock_recording_file_service.fetch_recording_file.side_effect = HTTPError("HTTP Error", response=mock_response)
        with self.assertRaises(SalesOpsPDSRecordingFileManager.NeedRetryException):
            self.manager.fetch_recording_file(self.reclink)

    def test_fetch_recording_file_http_error_500(self):
        mock_response = mock.MagicMock()
        mock_response.status_code = 500
        self.mock_recording_file_service.fetch_recording_file.side_effect = HTTPError("HTTP Error", response=mock_response)
        with self.assertRaises(SalesOpsPDSRecordingFileManager.NeedRetryException):
            self.manager.fetch_recording_file(self.reclink)

    def test_fetch_recording_file_http_error_400(self):
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        self.mock_recording_file_service.fetch_recording_file.side_effect = HTTPError("HTTP Error", response=mock_response)
        with self.assertRaises(HTTPError):
            self.manager.fetch_recording_file(self.reclink)
