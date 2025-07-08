from datetime import datetime
from unittest import mock

from factory import Iterator
from django.test import TestCase
from django.utils import timezone

from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.sales_ops.constants import CustomerType
from juloserver.sales_ops_pds.tests.factories import (
    SalesOpsLineupAIRudderDataFactory,
    AIRudderAgentGroupMappingFactory,
    AIRudderDialerTaskGroupFactory,
    AIRudderDialerTaskUploadFactory,
    AIRudderDialerTaskDownloadFactory,
)
from juloserver.sales_ops_pds.models import (
    AIRudderDialerTaskGroup,
    AIRudderDialerTaskUpload,
)
from juloserver.sales_ops_pds.constants import (
    FeatureNameConst,
    SalesOpsPDSTaskName,
)
from juloserver.sales_ops_pds.tasks import (
    init_create_sales_ops_pds_task,
    create_sales_ops_pds_task_subtask,
    send_create_task_request_to_airudder,
    init_download_sales_ops_pds_call_result_task,
    send_get_total_request_to_airudder,
    send_get_call_list_request_to_airudder,
)
from juloserver.sales_ops_pds.services.upload_data_services import (
    SalesOpsPDSUploadTask,
    AIRudderPDSUploadManager,
)
from juloserver.sales_ops_pds.services.download_data_services import (
    SalesOpsPDSDownloadTask,
    AIRudderPDSDownloadManager,
)
from juloserver.sales_ops_pds.services.store_data_services import (
    StoreSalesOpsPDSUploadData,
    StoreSalesOpsPDSDownloadData,
)

SUB_APP = 'juloserver.sales_ops_pds'


class TestInitSalesOpsPDSTask(TestCase):
    def setUp(self):
        self.bucket_code_a = "sales_ops_a"
        self.bucket_code_b = "sales_ops_b"
        self.setup_sales_ops_payload()
        self.setup_agent_group_mapping()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SALES_OPS_PDS,
            parameters={
                SalesOpsPDSTaskName.CREATE_TASK: True,
                SalesOpsPDSTaskName.DOWNLOAD_CALL_RESULT: True,
                SalesOpsPDSTaskName.DOWNLOAD_RECORDING_FILE: True,
                SalesOpsPDSTaskName.DOWNLOAD_LIMIT: 50
            },
        )

    def setup_sales_ops_payload(self):
        self.data = SalesOpsLineupAIRudderDataFactory.create_batch(
            5,
            bucket_code=Iterator([
                self.bucket_code_a, self.bucket_code_a, self.bucket_code_a,
                self.bucket_code_b, self.bucket_code_b
            ]),
            customer_type=Iterator([
                CustomerType.FTC, CustomerType.REPEAT_NO_OS, CustomerType.REPEAT_NO_OS,
                CustomerType.REPEAT_OS, CustomerType.REPEAT_OS
            ]),
            account_id=Iterator(range(5))
        )

    def setup_agent_group_mapping(self):
        self.agent_group_mappings = AIRudderAgentGroupMappingFactory.create_batch(
            6,
            bucket_code=Iterator([
                "sales_ops_a", "sales_ops_a", "sales_ops_a",
                "sales_ops_b", "sales_ops_b", "sales_ops_b"
            ]),
            customer_type=Iterator([
                CustomerType.FTC, CustomerType.REPEAT_OS, CustomerType.REPEAT_NO_OS,
                CustomerType.FTC, CustomerType.REPEAT_OS, CustomerType.REPEAT_NO_OS
            ]),
            agent_group_name=Iterator([
                "sales_ops_a_ftc", "sales_ops_a_repeat_no_os", "sales_ops_a_repeat_os",
                "sales_ops_b_ftc", "sales_ops_b_repeat_no_os", "sales_ops_b_repeat_os"
            ]),
            is_active=True
        )

    @mock.patch(f'{SUB_APP}.tasks.create_sales_ops_pds_task_subtask.delay')
    def test_init_sales_ops_pds_task(self, mock_create_subtask):
        init_create_sales_ops_pds_task()

        groups = AIRudderDialerTaskGroup.objects.all()
        self.assertEqual(len(groups), 3)

        bucket_sales_ops_a_ftc = AIRudderDialerTaskGroup.objects.filter(
            bucket_code=self.bucket_code_a,
            customer_type=CustomerType.FTC,
        ).last()
        self.assertEqual(bucket_sales_ops_a_ftc.total, 1)
        bucket_sales_ops_a_repeat_no_os = AIRudderDialerTaskGroup.objects.filter(
            bucket_code=self.bucket_code_a,
            customer_type=CustomerType.REPEAT_NO_OS,
        ).last()
        self.assertEqual(bucket_sales_ops_a_repeat_no_os.total, 2)
        bucket_sales_ops_b_repeat_os = AIRudderDialerTaskGroup.objects.filter(
            bucket_code=self.bucket_code_b,
            customer_type=CustomerType.REPEAT_OS,
        ).last()
        self.assertEqual(bucket_sales_ops_b_repeat_os.total, 2)

        calls = [
            mock.call(
                dialer_task_group_id=bucket_sales_ops_a_ftc.id,
                sub_account_ids=[0],
                batch_number=1
            ),
            mock.call(
                dialer_task_group_id=bucket_sales_ops_a_repeat_no_os.id,
                sub_account_ids=[1, 2],
                batch_number=1
            ),
            mock.call(
                dialer_task_group_id=bucket_sales_ops_b_repeat_os.id,
                sub_account_ids=[3, 4],
                batch_number=1
            )
        ]
        mock_create_subtask.assert_has_calls(calls, any_order=True)


    @mock.patch(f'{SUB_APP}.constants.SalesOpsPDSUploadConst.UPLOAD_BATCH_SIZE', 1)
    @mock.patch(f'{SUB_APP}.tasks.create_sales_ops_pds_task_subtask.delay')
    def test_init_sales_ops_pds_task_by_batch(self, mock_create_subtask):
        init_create_sales_ops_pds_task()

        groups = AIRudderDialerTaskGroup.objects.all()
        self.assertEqual(len(groups), 3)

        bucket_sales_ops_a_ftc = AIRudderDialerTaskGroup.objects.filter(
            bucket_code=self.bucket_code_a,
            customer_type=CustomerType.FTC,
        ).last()
        self.assertEqual(bucket_sales_ops_a_ftc.total, 1)
        bucket_sales_ops_a_repeat_no_os = AIRudderDialerTaskGroup.objects.filter(
            bucket_code=self.bucket_code_a,
            customer_type=CustomerType.REPEAT_NO_OS,
        ).last()
        self.assertEqual(bucket_sales_ops_a_repeat_no_os.total, 2)
        bucket_sales_ops_b_repeat_os = AIRudderDialerTaskGroup.objects.filter(
            bucket_code=self.bucket_code_b,
            customer_type=CustomerType.REPEAT_OS,
        ).last()
        self.assertEqual(bucket_sales_ops_b_repeat_os.total, 2)

        calls = [
            mock.call(
                dialer_task_group_id=bucket_sales_ops_a_ftc.id,
                sub_account_ids=[0],
                batch_number=1
            ),
            mock.call(
                dialer_task_group_id=bucket_sales_ops_a_repeat_no_os.id,
                sub_account_ids=[1],
                batch_number=1
            ),
            mock.call(
                dialer_task_group_id=bucket_sales_ops_a_repeat_no_os.id,
                sub_account_ids=[2],
                batch_number=2
            ),
            mock.call(
                dialer_task_group_id=bucket_sales_ops_b_repeat_os.id,
                sub_account_ids=[3],
                batch_number=1
            ),
            mock.call(
                dialer_task_group_id=bucket_sales_ops_b_repeat_os.id,
                sub_account_ids=[4],
                batch_number=2
            )
        ]
        mock_create_subtask.assert_has_calls(calls, any_order=True)

    @mock.patch(f'{SUB_APP}.services.upload_data_services.SalesOpsPDSUploadTask')
    def test_init_sales_ops_pds_task_fs_off(self, mock_sales_ops_pds_task):
        self.feature_setting.update_safely(is_active=False)
        init_create_sales_ops_pds_task()

        mock_sales_ops_pds_task.return_value.init_create_sales_ops_pds_task.assert_not_called()

    @mock.patch.object(StoreSalesOpsPDSUploadData, "store_uploaded_data")
    @mock.patch(f'{SUB_APP}.tasks.send_create_task_request_to_airudder.delay')
    def test_create_sales_ops_pds_task_success(
        self, mock_request_to_airudder, mock_store_upload_data
    ):
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code=self.bucket_code_a,
            customer_type=CustomerType.FTC,
            agent_group_mapping=self.agent_group_mappings[1],
            total=2
        )
        create_sales_ops_pds_task_subtask(
            dialer_task_group_id=self.dialer_task_group.id,
            sub_account_ids=[1, 2],
            batch_number=2
        )

        dialer_task_upload = AIRudderDialerTaskUpload.objects.filter(
            dialer_task_group=self.dialer_task_group
        ).last()

        self.assertEqual(dialer_task_upload.total_uploaded, 2)
        self.assertEqual(dialer_task_upload.batch_number, 2)

        mock_store_upload_data.assert_called_once()
        mock_request_to_airudder.assert_called_once_with(
            dialer_task_upload_id=dialer_task_upload.id
        )


class TestInitSalesOpsPDSDownloadTask(TestCase):
    def setUp(self):
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=15
        )
        self.dialer_task_upload_1 = AIRudderDialerTaskUploadFactory(
            dialer_task_group = self.dialer_task_group,
            total_uploaded=5,
            batch_number=1
        )
        self.dialer_task_upload_2 = AIRudderDialerTaskUploadFactory(
            dialer_task_group = self.dialer_task_group,
            total_uploaded=5,
            batch_number=2
        )
        self.dialer_task_upload_3 = AIRudderDialerTaskUploadFactory(
            dialer_task_group = self.dialer_task_group,
            total_uploaded=5,
            batch_number=3,
        )
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SALES_OPS_PDS,
            parameters={
                SalesOpsPDSTaskName.CREATE_TASK: True,
                SalesOpsPDSTaskName.DOWNLOAD_CALL_RESULT: True,
                SalesOpsPDSTaskName.DOWNLOAD_RECORDING_FILE: True,
                SalesOpsPDSTaskName.DOWNLOAD_LIMIT: 50
            },
        )

    @mock.patch(f'{SUB_APP}.tasks.send_get_total_request_to_airudder.delay')
    def test_init_download_sales_ops_pds_call_result(self, mock_get_call_list):
        now = timezone.localtime(datetime(2024, 12, 4, 8, 15, 0))

        self.dialer_task_upload_1.update_safely(
            cdate=timezone.localtime(datetime(2024, 12, 4, 7, 30, 0)),
            task_id="abcxyz_1"
        )
        self.dialer_task_upload_2.update_safely(
            cdate=timezone.localtime(datetime(2024, 12, 4, 7, 30, 0)),
            task_id="abcxyz_2"
        )
        self.dialer_task_upload_3.update_safely(
            cdate=timezone.localtime(datetime(2024, 12, 4, 7, 30, 0)),
            task_id="abcxyz_3"
        )
        with mock.patch.object(timezone, "now", return_value=now):
            init_download_sales_ops_pds_call_result_task()

            calls = [
                mock.call(
                    dialer_task_upload_id=self.dialer_task_upload_1.id,
                    start_time=timezone.localtime(datetime(2024, 12, 4, 7, 0, 0)),
                    end_time=timezone.localtime(datetime(2024, 12, 4, 7, 59, 59))
                ),
                mock.call(
                    dialer_task_upload_id=self.dialer_task_upload_2.id,
                    start_time=timezone.localtime(datetime(2024, 12, 4, 7, 0, 0)),
                    end_time=timezone.localtime(datetime(2024, 12, 4, 7, 59, 59))
                ),
                mock.call(
                    dialer_task_upload_id=self.dialer_task_upload_3.id,
                    start_time=timezone.localtime(datetime(2024, 12, 4, 7, 0, 0)),
                    end_time=timezone.localtime(datetime(2024, 12, 4, 7, 59, 59))
                )
            ]
            mock_get_call_list.assert_has_calls(calls, any_order=True)

    @mock.patch(f'{SUB_APP}.tasks.send_get_total_request_to_airudder.delay')
    def test_init_download_sales_ops_pds_call_result_criteria(self, mock_get_call_list):
        now = timezone.localtime(datetime(2024, 12, 4, 8, 15, 0))

        self.dialer_task_upload_1.update_safely(
            cdate=timezone.localtime(datetime(2024, 12, 4, 7, 30, 0)),
            task_id="abcxyz_1"
        )
        self.dialer_task_upload_2.update_safely(
            cdate=timezone.localtime(datetime(2024, 12, 2, 7, 30, 0)),
            task_id="abcxyz_2"
        )
        self.dialer_task_upload_3.update_safely(
            cdate=timezone.localtime(datetime(2024, 12, 4, 7, 30, 0))
        )
        with mock.patch.object(timezone, "now", return_value=now):
            init_download_sales_ops_pds_call_result_task()

            mock_get_call_list.assert_called_once_with(
                dialer_task_upload_id=self.dialer_task_upload_1.id,
                start_time=timezone.localtime(datetime(2024, 12, 4, 7, 0, 0)),
                end_time=timezone.localtime(datetime(2024, 12, 4, 7, 59, 59))
            )

    @mock.patch(f'{SUB_APP}.services.download_data_services.SalesOpsPDSDownloadTask')
    def test_init_download_sales_ops_pds_call_result_fs_off(self, mock_sales_ops_pds_task):
        self.feature_setting.update_safely(is_active=False)
        init_download_sales_ops_pds_call_result_task()

        mock_sales_ops_pds_task.init_download_sales_ops_pds_call_result.assert_not_called()


class TestSendAIRudderCreateTaskRequestTask(TestCase):
    def setUp(self):
        self.uploaded_data = [
            {
                "PhoneNumber": "081279377937",
                "gender": "Pria",
                "fullname": "Tomato Capuchino",
                "available_limit": "5000000",
                "set_limit": "4000000",
                "customer_type": "repeat_os",
                "application_history_x190_cdate": "2024-11-12T13:34:45",
                "latest_loan_fund_transfer_ts": "2024-11-12T13:34:45",
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
            }
        ]
        self.agent_group_mapping = AIRudderAgentGroupMappingFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            agent_group_name="SalesOpsA_RepeatOs"
        )
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            agent_group_mapping=self.agent_group_mapping,
            total=1
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group = self.dialer_task_group,
            total_uploaded=1,
            batch_number=1
        )

    @mock.patch.object(SalesOpsPDSUploadTask, "record_uploaded_sales_ops_pds_data")
    @mock.patch.object(SalesOpsPDSUploadTask, "load_data_from_oss_file")
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadService')
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadManager')
    def test_create_task_request_success(
        self, mock_airruder_manager, mock_airudder_service, mock_load_data, mock_record_data
    ):
        mock_airudder_service.return_value._validate_strategy_config.return_value = {}
        mock_airruder_manager.return_value.create_task.return_value = "task-Id", []
        mock_load_data.return_value = self.uploaded_data

        send_create_task_request_to_airudder(
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        mock_airudder_service.assert_called_once_with(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            customer_list=self.uploaded_data,
            strategy_config=mock.ANY,
            batch_number=1
        )
        mock_airruder_manager.assert_called_once_with(
            airudder_upload_service=mock_airudder_service.return_value
        )
        mock_record_data.assert_called_once_with(
            dialer_task_upload=self.dialer_task_upload,
            total_successful=1,
            total_failed=0,
            task_id="task-Id",
            error_uploaded_data=[]
        )

    @mock.patch.object(StoreSalesOpsPDSUploadData, "store_failed_uploaded_data")
    @mock.patch.object(SalesOpsPDSUploadTask, "load_data_from_oss_file")
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadService')
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadManager')
    def test_create_task_request_success_without_error_data(
        self, mock_airruder_manager, mock_airudder_service,
        mock_load_data, mock_store_failed_data
    ):
        mock_airudder_service.return_value._validate_strategy_config.return_value = {}
        mock_airruder_manager.return_value.create_task.return_value = "task-Id", []
        mock_load_data.return_value = self.uploaded_data

        send_create_task_request_to_airudder(
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        self.dialer_task_upload.refresh_from_db()
        self.assertEqual(self.dialer_task_upload.total_successful, 1)
        self.assertEqual(self.dialer_task_upload.total_failed, 0)
        self.assertEqual(self.dialer_task_upload.task_id, "task-Id")
        mock_store_failed_data.assert_not_called()

    @mock.patch.object(StoreSalesOpsPDSUploadData, "store_failed_uploaded_data")
    @mock.patch.object(SalesOpsPDSUploadTask, "load_data_from_oss_file")
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadService')
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadManager')
    def test_create_task_request_success_with_error_data(
        self, mock_airruder_manager, mock_airudder_service,
        mock_load_data, mock_store_failed_data
    ):
        failed_data = [{
            "PhoneNumber": "081279377937",
            "gender": "Pria",
            "fullname": "Tomato Capuchino",
            "available_limit": "5000000",
            "set_limit": "4000000",
            "customer_type": "repeat_os",
            "application_history_x190_cdate": "2024-11-12T13:34:45",
            "latest_loan_fund_transfer_ts": "2024-11-12T13:34:45",
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
        mock_airudder_service.return_value._validate_strategy_config.return_value = {}
        mock_airruder_manager.return_value.create_task.return_value = \
            "task-Id", failed_data
        mock_load_data.return_value = self.uploaded_data

        send_create_task_request_to_airudder(
            dialer_task_upload_id=self.dialer_task_upload.id
        )
        self.dialer_task_upload.refresh_from_db()
        self.assertEqual(self.dialer_task_upload.total_successful, 0)
        self.assertEqual(self.dialer_task_upload.total_failed, 1)
        self.assertEqual(self.dialer_task_upload.task_id, "task-Id")
        mock_store_failed_data.assert_called_once()

    @mock.patch.object(SalesOpsPDSUploadTask, "load_data_from_oss_file")
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadService')
    @mock.patch(f'{SUB_APP}.services.upload_data_services.AIRudderPDSUploadManager')
    def test_create_task_request_retry(
        self, mock_airruder_manager, mock_airudder_service, mock_load_data
    ):
        mock_airudder_service.return_value._validate_strategy_config.return_value = {}
        mock_airruder_manager.NeedRetryException = AIRudderPDSUploadManager.NeedRetryException
        mock_airruder_manager.return_value.create_task.side_effect = (
            AIRudderPDSUploadManager.NeedRetryException("exception")
        )
        mock_load_data.return_value = self.uploaded_data

        with self.assertRaises(AIRudderPDSUploadManager.NeedRetryException):
            send_create_task_request_to_airudder(
                dialer_task_upload_id=self.dialer_task_upload.id
            )

class TestSendAIRudderGetTotalResultRequestTask(TestCase):
    def setUp(self):
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=5
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group = self.dialer_task_group,
            total_uploaded=5,
            total_successful=5,
            total_failed=0,
            batch_number=1,
            task_id="abcxyz_1"
        )
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
                    "set_limit": "1200000"
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
                "reclink": "",
                "customerName": "",
                "callResultType": "NoAnwsered",
                "callType": "auto",
                "customerInfo": {
                    "account_id": "1000002",
                    "customer_id": "1000000002",
                    "application_id": "2000000002",
                    "available_limit": "1500000",
                    "customer_id": "1000000000",
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
                    "set_limit": "1200000"
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

    @mock.patch.object(SalesOpsPDSDownloadTask, 'init_download_call_result_per_task')
    @mock.patch(f'{SUB_APP}.services.download_data_services.AIRudderPDSDownloadManager')
    def test_get_total_request_success(
        self, mock_airruder_manager, mock_download_call_result_per_task
    ):
        mock_airruder_manager.return_value.get_total.return_value = self.total

        start_time = datetime(2024, 12, 4, 8, 0, 0)
        end_time = datetime(2024, 12, 4, 8, 59, 59)

        send_get_total_request_to_airudder(
            dialer_task_upload_id=self.dialer_task_upload.id,
            start_time=start_time,
            end_time=end_time
        )

        mock_download_call_result_per_task.assert_called_once_with(
            dialer_task_upload=self.dialer_task_upload,
            total_downloaded=self.total,
            start_time=start_time,
            end_time=end_time
        )

    @mock.patch(f'{SUB_APP}.services.download_data_services.AIRudderPDSDownloadManager')
    def test_get_call_list_request_retry(self, mock_airruder_manager):
        mock_airruder_manager.NeedRetryException = AIRudderPDSDownloadManager.NeedRetryException
        mock_airruder_manager.return_value.get_total.side_effect = (
            AIRudderPDSDownloadManager.NeedRetryException("exception")
        )

        with self.assertRaises(AIRudderPDSDownloadManager.NeedRetryException):
            send_get_total_request_to_airudder(
                dialer_task_upload_id=self.dialer_task_upload.id,
                start_time=datetime(2024, 12, 4, 8, 0, 0),
                end_time=datetime(2024, 12, 4, 8, 59, 59)
            )


class TestSendAIRudderGetCallResultRequestTask(TestCase):
    def setUp(self):
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=5
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group = self.dialer_task_group,
            total_uploaded=5,
            total_successful=5,
            total_failed=0,
            batch_number=1,
            task_id="abcxyz_1"
        )
        self.dialer_task_download = AIRudderDialerTaskDownloadFactory(
            dialer_task_upload=self.dialer_task_upload,
            total_downloaded=2,
            time_range="2024-12-04T08:00:00Z_2024-12-04T08:59:59Z",
            offset=0,
            limit=2
        )
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
                "adminAct": [],
                "transferReason": "",
                "talkResult": "",
                "remark": "",
                "talkremarks": "",
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
                "talkResult": "",
                "remark": "",
                "talkremarks": "",
                "reclink": "",
                "customerName": "",
                "callResultType": "NoAnwsered",
                "callType": "auto",
                "customerInfo": {
                    "account_id": "1000002",
                    "customer_id": "1000000002",
                    "application_id": "2000000002",
                    "available_limit": "1500000",
                    "customer_id": "1000000000",
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

    @mock.patch.object(StoreSalesOpsPDSDownloadData, 'store_downloaded_data')
    @mock.patch.object(SalesOpsPDSDownloadTask, 'capture_call_result_data_to_sales_ops')
    @mock.patch(f'{SUB_APP}.services.download_data_services.AIRudderPDSDownloadManager')
    def test_get_call_list_request_success(
        self, mock_airruder_manager, mock_capture_call_result, mock_store_data
    ):
        mock_airruder_manager.return_value.get_total.return_value = self.total
        mock_airruder_manager.return_value.get_call_list.return_value = self.call_list

        start_time = datetime(2024, 12, 4, 8, 0, 0)
        end_time = datetime(2024, 12, 4, 8, 59, 59)

        send_get_call_list_request_to_airudder(
            dialer_task_download_id=self.dialer_task_download.id,
            start_time=start_time,
            end_time=end_time
        )

        mock_capture_call_result.assert_called_once()
        mock_store_data.assert_called_once()

    @mock.patch(f'{SUB_APP}.services.download_data_services.AIRudderPDSDownloadManager')
    def test_get_call_list_request_retry(self, mock_airruder_manager):
        mock_airruder_manager.NeedRetryException = AIRudderPDSDownloadManager.NeedRetryException
        mock_airruder_manager.return_value.get_total.return_value = self.total
        mock_airruder_manager.return_value.get_call_list.side_effect = (
            AIRudderPDSDownloadManager.NeedRetryException("exception")
        )

        with self.assertRaises(AIRudderPDSDownloadManager.NeedRetryException):
            send_get_call_list_request_to_airudder(
                dialer_task_download_id=self.dialer_task_download.id,
                start_time=datetime(2024, 12, 4, 8, 0, 0),
                end_time=datetime(2024, 12, 4, 8, 59, 59)
            )
