import os

from django.test import TestCase
from unittest import mock

from juloserver.julo.tests.factories import (
    FeatureSettingFactory
)
from juloserver.sales_ops_pds.constants import (
    FeatureNameConst,
    SalesOpsPDSConst,
)
from juloserver.sales_ops_pds.services.upload_data_services import SalesOpsPDSUploadTask
from juloserver.sales_ops_pds.tests.factories import (
    AIRudderDialerTaskGroupFactory,
    AIRudderDialerTaskUploadFactory,
)

SUB_APP = 'juloserver.sales_ops_pds'


class TestLoadSalesOpsPDSSetting(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS_AI_RUDDER_TASKS_STRATEGY_CONFIG,
            parameters={
                SalesOpsPDSConst.SalesOpsPDSSetting.START_TIME: "6:00",
                SalesOpsPDSConst.SalesOpsPDSSetting.AUTO_END_TIME: "17:00",
                SalesOpsPDSConst.SalesOpsPDSSetting.REST_TIMES: ["12:00", "13:00"],
                SalesOpsPDSConst.SalesOpsPDSSetting.AUTO_SLOT_FACTOR: "0",
                SalesOpsPDSConst.SalesOpsPDSSetting.MAX_LOST_RATE: "1.0",
                SalesOpsPDSConst.SalesOpsPDSSetting.RING_LIMIT: "0",
                SalesOpsPDSConst.SalesOpsPDSSetting.DIALING_MODE: "1",
                SalesOpsPDSConst.SalesOpsPDSSetting.DIALING_ORDER: ["phone_number"],
                SalesOpsPDSConst.SalesOpsPDSSetting.ACW_TIME: "10",
                SalesOpsPDSConst.SalesOpsPDSSetting.REPEAT_TIMES: "4",
                SalesOpsPDSConst.SalesOpsPDSSetting.BULK_CALL_INTERVAL: "100",
                SalesOpsPDSConst.SalesOpsPDSSetting.VOICEMAIL_CHECK: "0",
                SalesOpsPDSConst.SalesOpsPDSSetting.VOICEMAIL_CHECK_DURATION: "2000",
                SalesOpsPDSConst.SalesOpsPDSSetting.VOICEMAIL_HANDLE: "1"
            },
            is_active=False
        )

    def test_load_strategy_fs_turn_off(self):
        strategy_setting = SalesOpsPDSUploadTask().get_sales_ops_task_strategy_config()

        self.assertEqual(
            strategy_setting["start_time"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.START_TIME
        )
        self.assertEqual(
            strategy_setting["end_time"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.AUTO_END_TIME
        )
        self.assertEqual(
            strategy_setting["rest_times"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.REST_TIMES
        )
        self.assertEqual(
            strategy_setting["autoSlotFactor"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.AUTO_SLOT_FACTOR
        )
        self.assertEqual(
            strategy_setting["maxLostRate"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.MAX_LOST_RATE
        )
        self.assertEqual(
            strategy_setting["ringLimit"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.RING_LIMIT
        )
        self.assertEqual(
            strategy_setting["maxLostRate"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.MAX_LOST_RATE
        )
        self.assertEqual(
            strategy_setting["dialingMode"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.DIALING_MODE
        )
        self.assertEqual(
            strategy_setting["dialingOrder"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.DIALING_ORDER
        )
        self.assertEqual(
            strategy_setting["acwTime"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.ACW_TIME
        )
        self.assertEqual(
            strategy_setting["repeatTimes"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.REPEAT_TIMES
        )
        self.assertEqual(
            strategy_setting["bulkCallInterval"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.BULK_CALL_INTERVAL
        )
        self.assertEqual(
            strategy_setting["voiceCheck"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.VOICEMAIL_CHECK
        )
        self.assertEqual(
            strategy_setting["voiceCheckDuration"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.VOICEMAIL_CHECK_DURATION
        )
        self.assertEqual(
            strategy_setting["voiceHandle"],
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.VOICEMAIL_HANDLE
        )

    def test_load_strategy_fs_turn_on(self):
        self.feature_setting.update_safely(is_active=True)
        strategy_setting = SalesOpsPDSUploadTask().get_sales_ops_task_strategy_config()

        self.assertEqual(strategy_setting["start_time"], "6:00")
        self.assertEqual(strategy_setting["end_time"], "17:00")
        self.assertEqual(strategy_setting["rest_times"], ["12:00", "13:00"])
        self.assertEqual(strategy_setting["autoSlotFactor"], "0")
        self.assertEqual(strategy_setting["ringLimit"], "0")
        self.assertEqual(strategy_setting["maxLostRate"], "1.0")
        self.assertEqual(strategy_setting["dialingMode"], "1")
        self.assertEqual(strategy_setting["dialingOrder"], ["phone_number"])
        self.assertEqual(strategy_setting["acwTime"], "10")
        self.assertEqual(strategy_setting["repeatTimes"], "4")
        self.assertEqual(strategy_setting["bulkCallInterval"], "100")
        self.assertEqual(strategy_setting["voiceCheck"], "0")
        self.assertEqual(strategy_setting["voiceCheckDuration"], "2000")
        self.assertEqual(strategy_setting["voiceHandle"], "1")


class TestLoadDataFromOSS(TestCase):
    def setUp(self):
        self.dialer_task_group = AIRudderDialerTaskGroupFactory(
            bucket_code="sales_ops_a",
            customer_type="repeat_os",
            total=3
        )
        self.dialer_task_upload = AIRudderDialerTaskUploadFactory(
            dialer_task_group=self.dialer_task_group,
            total_uploaded=1,
            batch_number=1,
            upload_file_url="sales_ops_pds/upload/SalesOpsA_RepeatOs_20250121_070010_p1.csv"
        )
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

    @mock.patch('juloserver.sales_ops_pds.services.upload_data_services.get_file_from_oss')
    def test_load_data_from_oss_file(self, mock_get_file_from_oss):
        mock_file_stream = mock.MagicMock()
        mock_file_stream.content_type = 'text/csv'
        mock_file_stream.read.return_value = b"""PhoneNumber,gender,fullname,available_limit,set_limit,customer_type,application_history_x190_cdate,latest_loan_fund_transfer_ts,is_12m_user,is_high_value_user,kode_voucher,scheme,biaya_admin_sebelumnya,biaya_admin_baru,r_score,m_score,latest_active_dates,customer_id,application_id,account_id,data_date,partition_date,customer_segment,schema_amount,schema_loan_duration,cicilan_per_bulan_sebelumnya,cicilan_per_bulan_baru,saving_overall_after_np
081279377937,Pria,Tomato Capuchino,5000000,4000000,repeat_os,2024-11-12T13:34:45,2024-11-12T13:34:45,non_12M_user,average_value_user,PROMOCODE1234,abc,0.0007,0.09,1,1,2024-11-10,1000000001,2000000001,100001,2024-11-11,2024-11-11,segment_a,1000000,2,100,100,1"""
        mock_get_file_from_oss.return_value = mock_file_stream

        data = SalesOpsPDSUploadTask().load_data_from_oss_file(
            dialer_task_upload=self.dialer_task_upload
        )
        self.assertEqual(data, self.uploaded_data)
