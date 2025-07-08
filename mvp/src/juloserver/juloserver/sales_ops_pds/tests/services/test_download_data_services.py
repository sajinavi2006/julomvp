import pytz
from datetime import datetime
from unittest import mock

from django.utils import timezone
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
)
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.sales_ops.models import SalesOpsAgentAssignment
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsAgentAssignmentFactory,
)
from juloserver.sales_ops_pds.tests.factories import (
    AIRudderDialerTaskGroupFactory,
    AIRudderDialerTaskUploadFactory,
)
from juloserver.sales_ops_pds.services.download_data_services import (
    SalesOpsPDSDownloadTask
)
from juloserver.sales_ops_pds.services.store_data_services import (
    StoreSalesOpsPDSDownloadData
)
from juloserver.sales_ops_pds.models import AIRudderDialerTaskDownload
from juloserver.sales_ops_pds.constants import SalesOpsPDSDataStoreType

SUB_APP = 'juloserver.sales_ops_pds'

class TestDownloadDataServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account
        )
        self.lineup = SalesOpsLineupFactory(account=self.account, is_active=True)
        self.agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup=self.lineup,
            is_active=False,
            is_rpc=False,
            non_rpc_attempt=2,
            completed_date=datetime(2024, 12, 3, 12, 34, 45),
        )
        self.agent_user = AuthUserFactory(username='agent_sales_ops')
        self.agent = AgentFactory(user=self.agent_user)
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
        self.total = 1
        self.call_list = [
            {
                "talkDuration": 25,
                "seScore": 0,
                "holdDuration": 0,
                "hangupReason": 12,
                "nthCall": 1,
                "taskId": "abcd0123456789",
                "taskName": "SalesOpsA_RepeatOs",
                "callid": "abcd0123456789abcd",
                "caller": "",
                "phoneNumber": "+62899748000",
                "calltime": "2024-12-27T08:45:11Z",
                "ringtime": "2024-12-27T08:45:14Z",
                "answertime": "",
                "talktime": "",
                "endtime": "2024-12-27T08:46:14Z",
                "biztype": "Tech_Test",
                "agentName": "agent_sales_ops",
                "OrgName": "AICC_JULO_PDS",
                "TaskStartTime": "2024-12-27T08:12:00Z",
                "talkResult": "",
                "remark": "",
                "talkremarks": "",
                "customerName": "",
                "callResultType": "SuccAgentHangup",
                "callType": "auto",
                "mainNumber": "+62899748000",
                "phoneTag": "",
                "waitingDuration": 2,
                "talkedTime": 23,
                "seText": "No Survey Results",
                "adminAct": [],
                "reclink": "",
                "wfContactId": "",
                "transferReason": "",
                "customerInfo": {
                    "account_id": str(self.account.id),
                    "customer_id": str(self.customer.id),
                    "application_id": str(self.application.id),
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
                        "title": "Level 1",
                        "groupName": "",
                        "value": "Connected"
                    },
                    {
                        "title": "Level 2",
                        "groupName": "",
                        "value": "rpc_1"
                    },
                    {
                        "title": "Level 3",
                        "groupName": "",
                        "value": "rpc_interested"
                    }
                ]
            }
        ]

    @mock.patch(f'{SUB_APP}.services.download_data_services.get_download_limit_fs_params')
    def test_get_call_list_per_task(self, mock_download_limit):
        mock_download_limit.return_value = 2

        SalesOpsPDSDownloadTask().init_download_call_result_per_task(
            total_downloaded=2,
            dialer_task_upload=self.dialer_task_upload,
            start_time=datetime(2024, 12, 4, 8, 0, 0),
            end_time=datetime(2024, 12, 4, 8, 59, 59)
        )

        dialer_task_download = AIRudderDialerTaskDownload.objects.filter(
            dialer_task_upload=self.dialer_task_upload
        ).last()

        self.assertEqual(dialer_task_download.total_downloaded, 2)
        self.assertEqual(
            dialer_task_download.time_range,
            "2024-12-04T08:00:00Z_2024-12-04T08:59:59Z"
        )
        self.assertEqual(dialer_task_download.offset, 0)
        self.assertEqual(dialer_task_download.limit, 2)

    @mock.patch(f'{SUB_APP}.services.download_data_services.get_download_limit_fs_params')
    @mock.patch(f'{SUB_APP}.tasks.send_get_call_list_request_to_airudder.delay')
    def test_get_call_list_per_task_with_pagination(
        self, mock_get_call_list, mock_download_limit
    ):
        mock_download_limit.return_value = 2

        start_time = datetime(2024, 12, 4, 8, 0, 0)
        end_time = datetime(2024, 12, 4, 8, 59, 59)

        SalesOpsPDSDownloadTask().init_download_call_result_per_task(
            total_downloaded=4,
            dialer_task_upload=self.dialer_task_upload,
            start_time=start_time,
            end_time=end_time
        )

        dialer_task_downloads = AIRudderDialerTaskDownload.objects.filter(
            dialer_task_upload=self.dialer_task_upload
        )
        self.assertEqual(len(dialer_task_downloads), 2)

        calls = [
            mock.call(
                dialer_task_download_id=dialer_task_downloads[0].id,
                start_time=start_time,
                end_time=end_time
            ),
            mock.call(
                dialer_task_download_id=dialer_task_downloads[1].id,
                start_time=start_time,
                end_time=end_time
            )
        ]
        mock_get_call_list.assert_has_calls(calls, any_order=True)

    def test_evaluate_is_rpc_from_call_result(self):
        call_result = {
            "callResultType": "SuccAgentHangup",
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rpc_1"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": "rpc_interested"
                }
            ]
        }
        serivce = SalesOpsPDSDownloadTask()
        self.assertTrue(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({"callResultType": "SuccUserHangup"})
        self.assertTrue(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rpc_1"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": "rpc_consider"
                }
            ]
        })
        self.assertTrue(serivce.map_airudder_call_status_to_rpc(call_result))

    def test_evaluate_is_non_rpc_from_call_result(self):
        call_result = {
            "callResultType": "SuccAgentHangup",
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
        serivce = SalesOpsPDSDownloadTask()
        self.assertFalse(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({"callResultType": "NoAnswered"})
        self.assertFalse(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rpc_2"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": "rpc_hangup"
                }
            ]
        })
        self.assertFalse(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rpc_2"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": "rpc_moveto_cs"
                }
            ]
        })
        self.assertFalse(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rejected"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": ""
                }
            ]
        })
        self.assertFalse(serivce.map_airudder_call_status_to_rpc(call_result))

        call_result.update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "wpc"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": ""
                }
            ]
        })
        self.assertFalse(serivce.map_airudder_call_status_to_rpc(call_result))

    @mock.patch("django.utils.timezone.now")
    def test_capture_call_result_rpc(self, mock_now):
        mock_now.return_value = timezone.localtime(datetime(2024, 12, 27, 8, 42, 14))

        SalesOpsPDSDownloadTask().capture_call_result_data_to_sales_ops(
            call_list=self.call_list
        )

        agent_assignment = SalesOpsAgentAssignment.objects.filter(
            lineup_id=self.lineup.id
        ).last()

        self.assertFalse(agent_assignment.is_active)
        self.assertEqual(
            agent_assignment.assignment_date,
            timezone.localtime(datetime(2024, 12, 27, 8, 42, 14))
        )
        self.assertEqual(
            agent_assignment.completed_date,
            datetime(2024, 12, 27, 8, 46, 14, tzinfo=pytz.UTC)
        )
        self.assertTrue(agent_assignment.is_rpc)
        self.assertEqual(agent_assignment.non_rpc_attempt, 0)

    @mock.patch("django.utils.timezone.now")
    def test_capture_call_result_non_rpc(self, mock_now):
        mock_now.return_value = timezone.localtime(datetime(2024, 12, 27, 8, 42, 14))
        self.call_list[0].update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rpc_2"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": "rpc_call_back_later"
                }
            ]
        })
        self.lineup.update_safely(
            latest_agent_assignment_id=self.agent_assignment.id
        )

        SalesOpsPDSDownloadTask().capture_call_result_data_to_sales_ops(
            call_list=self.call_list
        )

        agent_assignment = SalesOpsAgentAssignment.objects.filter(
            lineup_id=self.lineup.id
        ).last()

        self.assertFalse(agent_assignment.is_active)
        self.assertEqual(
            agent_assignment.assignment_date,
            timezone.localtime(datetime(2024, 12, 27, 8, 42, 14))
        )
        self.assertEqual(
            agent_assignment.completed_date,
            datetime(2024, 12, 27, 8, 46, 14, tzinfo=pytz.UTC)
        )
        self.assertEqual(agent_assignment.agent_id, self.agent.id)
        self.assertEqual(agent_assignment.agent_name, self.agent.user.username)
        self.assertFalse(agent_assignment.is_rpc, False)
        self.assertEqual(agent_assignment.non_rpc_attempt, 3)

    @mock.patch("django.utils.timezone.now")
    def test_capture_call_result_non_rpc_no_agent_found(self, mock_now):
        mock_now.return_value = timezone.localtime(datetime(2024, 12, 27, 8, 42, 14))
        self.call_list[0].update({
            "customizeResults": [
                {
                    "title": "Level 1",
                    "groupName": "",
                    "value": "Connected"
                },
                {
                    "title": "Level 2",
                    "groupName": "",
                    "value": "rpc_2"
                },
                {
                    "title": "Level 3",
                    "groupName": "",
                    "value": "rpc_call_back_later"
                }
            ],
            "agentName": ""
        })
        self.lineup.update_safely(
            latest_agent_assignment_id=self.agent_assignment.id
        )

        SalesOpsPDSDownloadTask().capture_call_result_data_to_sales_ops(
            call_list=self.call_list
        )

        agent_assignment = SalesOpsAgentAssignment.objects.filter(
            lineup_id=self.lineup.id
        ).last()

        self.assertFalse(agent_assignment.is_active)
        self.assertEqual(
            agent_assignment.assignment_date,
            timezone.localtime(datetime(2024, 12, 27, 8, 42, 14))
        )
        self.assertEqual(
            agent_assignment.completed_date,
            datetime(2024, 12, 27, 8, 46, 14, tzinfo=pytz.UTC)
        )
        self.assertEqual(agent_assignment.agent_id, 0)
        self.assertEqual(agent_assignment.agent_name, '')
        self.assertFalse(agent_assignment.is_rpc, False)
        self.assertEqual(agent_assignment.non_rpc_attempt, 3)

    @mock.patch("django.utils.timezone.now")
    @mock.patch("juloserver.sales_ops_pds.services.store_data_services.upload_file_to_oss")
    def test_store_download_call_result(self, mock_upload_oss, mock_now):
        mock_now.return_value = timezone.localtime(datetime(2024, 12, 28, 12, 23, 34))

        dialer_task_download = AIRudderDialerTaskDownload.objects.create(
            dialer_task_upload=self.dialer_task_upload,
            total_downloaded=1,
            time_range="2024-12-28T08:00:00Z_2024-12-28T08:59:59Z",
            limit=50,
            offset=0
        )
        StoreSalesOpsPDSDownloadData(
            data=self.call_list,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=dialer_task_download.id
        ).store_downloaded_data()

        dialer_task_download.refresh_from_db()
        mock_upload_oss.assert_called_once()
        self.assertEqual(
            dialer_task_download.download_file_url,
            "{prefix}/{file_name}".format(
                prefix="sales_ops_pds/download/20241228",
                file_name="SalesOpsA_RepeatOs_2024-12-28T08:00:00Z_2024-12-28T08:59:59Z_o0_l50.csv"
            )
        )
