import json

import mock
from django.test.testcases import TestCase
from rest_framework.status import HTTP_201_CREATED
from rest_framework.test import APIClient, APITestCase

from juloserver.bpjs.clients import AnaserverClient, TongdunClient
from juloserver.bpjs.constants import TongdunCodes
from juloserver.bpjs.models import BpjsTask
from juloserver.bpjs.services import (
    create_or_update_bpjs_task_from_tongdun_callback,
    generate_bpjs_login_url_via_tongdun,
    retrieve_and_store_bpjs_data,
)
from juloserver.bpjs.tests.factories import BpjsTaskFactory
from juloserver.julo.tests.factories import ApplicationFactory, CustomerFactory


class TestLoginUrl(TestCase):
    def test_generate_bpjs_login_url_via_tongdun(self):
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        kwargs = {
            "customer_id": customer.id,
            "application_id": application.id,
            "app_type": "app",
        }
        login_url = generate_bpjs_login_url_via_tongdun(**kwargs)

        self.assertTrue(len(login_url) > 0)

    def test_generate_bpjs_url(self):
        """
        Test for Login Generate URL
        """

        customer = CustomerFactory()
        application = ApplicationFactory()
        response = self.client.get(
            "/api/bpjs/v1/login/app/{}/{}/".format(customer.id, application.id)
        )
        self.assertIsNotNone(response)

        response = self.client.get("/api/bpjs/v1/login/app/{}/2000001409/".format(customer.id))
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/api/bpjs/v1/login/app/1000001350/2000001409/")
        self.assertEqual(response.status_code, 400)


class TestTongdunTask(TestCase):
    def get_data(self):
        data = {
            "code": TongdunCodes.TONGDUN_TASK_SUBMIT_SUCCESS_CODE,
            "message": "The task has been submitted successfully",
            "task_id": "TASKPR105002202003061757090321543847",
            "data": {
                "identity_code": None,
                "created_time": "2018-01-30 11:36:34",
                "channel_src": None,
                "user_mobile": None,
                "task_data": None,
                "user_name": None,
                "real_name": None,
                "channel_code": "103002",
                "channel_type": "SOCIAL",
                "channel_attr": None,
                "lost_data": None,
            },
        }
        return data

    def create_or_update_bpjs_task_from_tongdun_callback(self, passback_params, notify_data):
        customer_id, application_id, data_source, page = passback_params.split("_")
        data = {
            "code": notify_data["code"],
            "task_id": notify_data["task_id"],
            "message": notify_data["message"],
        }
        response = create_or_update_bpjs_task_from_tongdun_callback(
            data, customer_id, application_id, data_source
        )

        return response

    @mock.patch("juloserver.bpjs.views.view_v1.process_post_connect_bpjs_success")
    def test_create_or_update_bpjs_task_from_tongdun_callback(
        self, mock_process_post_connect_bpjs_success
    ):
        passback_params = {"passback_params": ""}
        response = self.client.post("/api/bpjs/v1/callback/tongdun/task", data=passback_params)
        assert response.status_code == 200

        data1 = {"notify_data": "", "passback_params": "1000001350_2000001409_app_julo"}
        response = self.client.post("/api/bpjs/v1/callback/tongdun/task", data=data1)
        assert response.status_code == 200
        passback_params = "1000001350_2000001409_web_1"
        data6 = {
            "code": 0,
            "message": "The task has been submitted successfully",
            "task_id": "",
            "data": {
                "identity_code": "",
                "created_time": "2018-01-30 11:36:34",
                "channel_src": "",
                "user_mobile": "",
                "task_data": "",
                "user_name": "",
                "real_name": "",
                "channel_code": "103002",
                "channel_type": "SOCIAL",
                "channel_attr": "",
                "lost_data": "",
            },
        }
        data7 = {"notify_data": json.dumps(data6), "passback_params": passback_params}

        response = self.client.post("/api/bpjs/v1/callback/tongdun/task", data=data7)

        assert response.status_code == 200

        data2 = {
            "code": 8,
            "message": "The task has been submitted successfully",
            "task_id": "TASKPR105002202004151222090900200666",
            "data": {
                "identity_code": "",
                "created_time": "2018-01-30 11:36:34",
                "channel_src": "",
                "user_mobile": "",
                "task_data": "",
                "user_name": "",
                "real_name": "",
                "channel_code": "103002",
                "channel_type": "SOCIAL",
                "channel_attr": "",
                "lost_data": "",
            },
        }

        data3 = {"notify_data": json.dumps(data2), "passback_params": passback_params}
        response = self.client.post("/api/bpjs/v1/callback/tongdun/task", data=data3)

        assert response.status_code == 200

        data4 = {
            "code": 1,
            "message": "The task has been submitted successfully",
            "task_id": "TASKPR105002202004151222090900200666",
            "data": {
                "identity_code": "",
                "created_time": "2018-01-30 11:36:34",
                "channel_src": "",
                "user_mobile": "",
                "task_data": "",
                "user_name": "",
                "real_name": "",
                "channel_code": "103002",
                "channel_type": "SOCIAL",
                "channel_attr": "",
                "lost_data": "",
            },
        }
        data5 = {"notify_data": json.dumps(data4), "passback_params": passback_params}
        bpjs_task_dict = dict(
            customer_id=1000001350,
            application_id=2000001409,
            task_id="TASKPR105002202004151222090900200666",
        )
        BpjsTask.objects.create(**bpjs_task_dict)
        response = self.client.post("/api/bpjs/v1/callback/tongdun/task", data=data5)

        assert response.status_code == 200
        data8 = {
            "code": 0,
            "message": "The task has been submitted successfully",
            "task_id": "TASKPR105002202004151222090900200666",
            "data": {
                "identity_code": "",
                "created_time": "2018-01-30 11:36:34",
                "channel_src": "",
                "user_mobile": "",
                "task_data": "",
                "user_name": "",
                "real_name": "",
                "channel_code": "103002",
                "channel_type": "SOCIAL",
                "channel_attr": "",
                "lost_data": "",
            },
        }
        data9 = {"notify_data": json.dumps(data8), "passback_params": passback_params}
        response = self.client.post("/api/bpjs/v1/callback/tongdun/task", data=data9)
        assert response.status_code == 200
        notify_data = self.get_data()
        bpjs_task_dict = dict(
            customer_id=1000001350,
            application_id=2000001409,
            task_id=notify_data["task_id"],
        )
        BpjsTask.objects.create(**bpjs_task_dict)
        response = self.create_or_update_bpjs_task_from_tongdun_callback(
            "1000001350_2000001409_app_julo", notify_data
        )
        self.assertEqual(response, TongdunCodes.TONGDUN_TASK_SUBMIT_SUCCESS_CODE)


class JuloBPJSClient(APIClient):
    def _mock_response(self, status=200, json_data=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp

    def mocked_ana_response(self):
        return self._mock_response(status=201, json_data={"success": "Data Created Successfully"})

    def mocked_bpjs_response(self):
        return self._mock_response(status=201, json_data={"success": "Data fetched Successfully"})


class TestRetrieveAndStoreBpjsData(TestCase):
    client_class = JuloBPJSClient

    @mock.patch("juloserver.bpjs.clients.AnaserverClient.send_bpjs_data")
    @mock.patch.object(TongdunClient, "get_bpjs_data")
    def test_retrieve_and_store_bpjs_data(self, mocked_get, mock_send):
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        task = BpjsTaskFactory(application=application)
        mock_send.return_value = self.client.mocked_ana_response()
        mocked_get.return_value = self.client.mocked_bpjs_response()
        response = retrieve_and_store_bpjs_data(task.id, customer.id, application.id)
        self.assertEqual(response.status_code, HTTP_201_CREATED)

    @mock.patch.object(TongdunClient, "get_bpjs_data")
    def test_get_bpjs_data(self, mocked_get):
        customer_id = 1000001350
        application_id = 2000001409
        task_id = "TASKPR105002202003061757090321543847"

        response = TongdunClient.get_bpjs_data(task_id, customer_id, application_id)
        self.assertIsNotNone(response)
