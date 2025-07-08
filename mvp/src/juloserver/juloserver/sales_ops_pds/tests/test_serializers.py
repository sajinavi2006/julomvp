import pytz
from datetime import datetime
from unittest import mock

from rest_framework.exceptions import ValidationError

from django.utils import timezone
from django.test import TestCase

from juloserver.sales_ops_pds.serializers import (
    SalesOpsLineupAIRudderDataSerializer,
    AIRudderCallResultSerializer,
)


class TestSalesOpsLineupAIRudderDataSerializer(TestCase):
    def setUp(self):
        self.data = [{
            "cdate": mock.ANY,
            "udate": mock.ANY,
            "id": mock.ANY,
            "bucket_code": "sales_ops_a",
            "mobile_phone_1": "081279377937",
            "gender": "Pria",
            "fullname": "Tomato Capuchino",
            "available_limit": "5000000",
            "set_limit": "4000000",
            "customer_type": "repeat_os",
            "application_history_x190_cdate": datetime(2024, 11, 12, 13, 34, 45, tzinfo=pytz.UTC),
            "latest_loan_fund_transfer_ts": datetime(2024, 11, 12, 13, 34, 45, tzinfo=pytz.UTC),
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

    def test_transform_phone_number(self):
        serializer = SalesOpsLineupAIRudderDataSerializer(data=self.data, many=True)
        self.assertTrue(serializer.is_valid())
        data = serializer.data[0]
        self.assertEqual(data["PhoneNumber"], "+6281279377937")

    def test_remove_unused_field(self):
        serializer = SalesOpsLineupAIRudderDataSerializer(data=self.data, many=True)
        self.assertTrue(serializer.is_valid())
        data_keys = list(serializer.data[0].keys())

        excluded_fields = ["cdate", "udate", "id", "bucket_code", "mobile_phone_1"]
        for excluded_field in excluded_fields:
            self.assertTrue(excluded_field not in data_keys)


class TestAIRudderCallResultSerializer(TestCase):
    def setUp(self):
        self.data = [
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
                "agentName": "",
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
                ],
                "customerInfo": {
                    "account_id": "1000000",
                    "application_history_x190_cdate": "2023-12-11T09:08:29.927513Z",
                    "application_id": "2000000000",
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
                "distRuleAgent": ""
            }
        ]

    def test_validated_data(self):
        serializer = AIRudderCallResultSerializer(data=self.data, many=True)
        self.assertTrue(serializer.is_valid())

    def test_format_customer_info_fields(self):
        serializer = AIRudderCallResultSerializer(data=self.data, many=True)
        self.assertTrue(serializer.is_valid())
        data = serializer.validated_data[0]

        self.assertEqual(data["account_id"], "1000000")
        self.assertEqual(data["application_id"], "2000000000")
        self.assertEqual(data["customer_id"], "1000000000")
        self.assertEqual(data["application_history_x190_cdate"], "2023-12-11T09:08:29.927513Z")
        self.assertEqual(data["available_limit"], "1500000")
        self.assertEqual(data["set_limit"], "1200000")
        self.assertEqual(data["customer_type"], "repeat_os")
        self.assertEqual(data["data_date"], "2024-11-21")
        self.assertEqual(data["fullname"], "Prod Only")
        self.assertEqual(data["gender"], "Pria")
        self.assertEqual(data["is_12M_user"], "non_12M_user")
        self.assertEqual(data["is_high_value_user"], "average_value_user")
        self.assertEqual(data["latest_active_dates"], "2023-12-11")
        self.assertEqual(data["latest_loan_fund_transfer_ts"], "2019-05-15T02:15:09.116700Z")
        self.assertEqual(data["m_score"], "1")
        self.assertEqual(data["r_score"], "1")


    def test_format_call_result_fields(self):
        serializer = AIRudderCallResultSerializer(data=self.data, many=True)
        self.assertTrue(serializer.is_valid())
        data = serializer.validated_data[0]

        self.assertEqual(data["level_1"], "Connected")
        self.assertEqual(data["level_2"], "rpc_1")
        self.assertEqual(data["level_3"], "rpc_interested")
