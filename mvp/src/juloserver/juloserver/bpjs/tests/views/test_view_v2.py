import json
from unittest.mock import Mock, MagicMock
from urllib.parse import urlencode
from django.conf import settings
from django.test import TestCase
from mock import patch
from requests.models import Response
from rest_framework.test import APIClient, APITestCase

from juloserver.bpjs import get_brick_client
from juloserver.bpjs.clients import BrickClient
from juloserver.bpjs.models import BpjsAPILog
from juloserver.bpjs.services import Bpjs
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
)
from juloserver.bpjs.constants import BrickSetupClient

requests = Mock()


class TestBpjsGenerateToken(APITestCase):
    def setUp(self):
        self.client_id = "client_id_test"
        self.client_secret = "client_secret_test"
        self.base_url = "base_url_local"

    @patch("juloserver.bpjs.clients.BrickClient.get_auth_token")
    def test_check_fail_credentials_access_token(self, mock_get):
        """
        Test if client id and client secret not match.
        expected result endpoint response status_code 500.
        """

        response = Response()
        response.status_code = 500
        response._content = b'{ "status" : "failure" }'
        mock_response = {"response": response}
        mock_get.return_value = mock_response
        # check if client id and client_secret is not match.
        result = BrickClient(self.client_id, self.client_secret, self.base_url).get_auth_token()

        assert mock_get.called
        assert result["response"].status_code == 500


class TestViewGenerateToken(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.content_type = "application/x-www-form-urlencoded"
        self.base_url = "/api/bpjs/v2/public-access-token"

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        self.application.update_safely(
            application_status_id=100,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)

    def test_hit_failure_param_none_public_token(self):
        """
        Test with scenario application is None
        """

        payload_data = {"application_id": None}
        response = self.client.post(
            self.base_url, data=payload_data, content_type=self.content_type
        )
        response_error_message = response.json()["errors"]

        self.assertEqual(["param is empty!"], response_error_message)

    def test_hit_failure_param_alfanumeric(self):
        """
        Test with scenario application is Alfanumeric
        """

        data = urlencode({"application_id": "12313131qadasda"})
        response = self.client.post(self.base_url, data, content_type=self.content_type)
        response_error_message = response.json()["errors"]

        self.assertEqual(["param must number!"], response_error_message)

    @patch("juloserver.bpjs.clients.requests")
    def test_hit_success_param(self, mock_request):
        """
        Test with scenario application is not None
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": 200,
            "message": "OK",
            "data": {"access_token": "abc"},
        }
        mock_request.get.return_value = mock_response

        data = urlencode({"application_id": str(self.application.id)})
        response = self.client.post(self.base_url, data, content_type=self.content_type)

        api_log_data = BpjsAPILog.objects.filter(application_id=self.application.id).last()
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content.decode('utf-8'))
        self.assertEqual(content['data']['access_token'], 'abc')
        self.assertEqual(api_log_data.application_status_code, 100)

    def test_hit_with_unauthorized_application(self):

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(customer=customer, workflow=self.workflow)

        data = urlencode({"application_id": str(application.id)})
        response = self.client.post(self.base_url, data, content_type=self.content_type)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)
        content = json.loads(response.content.decode('utf-8'))
        self.assertFalse(content['success'])
        self.assertIsNone(content['data'])
        self.assertEqual(content['errors'][0], "Customer not authorized to generate token.")

    @patch("juloserver.bpjs.clients.BrickClient.get_auth_token")
    def test_check_get_public_access_token_success(self, mock_get):
        """
        Test scenario success response for Brick client.
        """

        client_id = "client_id_test"
        client_secret = "client_secret_test"
        base_url = "base_url_local"
        response = Response()
        response.status_code = 200
        response._content = b'{ "status" : "success" }'

        mock_response = {"response": response}
        mock_get.return_value = mock_response

        result = BrickClient(client_id, client_secret, base_url).get_auth_token()

        assert mock_get.called
        assert result["response"].status_code == 200


class TestLoggingAPI(TestCase):
    def setUp(self):

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_condition_failure(self, mock):
        """
        Test for scenario failure and save it to logging by response.
        """

        response = Response()
        response.status_code = 500
        response.url = "/testing"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"timestamp":"2021-12-28T08:42:32.228+00:00",'
            b'"status":500,'
            b'"error":"Internal Server Error",'
            b'"path":"v1/auth/token"}'
        )
        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        data_log = {
            "application_id": self.application.id,
            "service_provider": "brick",
            "api_type": "POST",
            "http_status_code": str(result.status_code),
            "query_params": str(result.url),
            "request": "header: " + str(result.headers) + " body: " + str(result.body),
            "response": str(result.json()),
            "error_message": str(result.json()["error"]),
        }
        bpjs = Bpjs(application=self.application, provider="brick")
        bpjs.log_api_call(**data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()

        assert mock.called
        self.assertTrue(is_exists)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_condition_success(self, mock):
        """
        Test for scenario success (200 OK) and save it to logging by response.
        """

        response = Response()
        response.status_code = 200
        response.url = "/testing"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"status":200,'
            b'"message":"OK",'
            b'"data":{"access_token":"public-sandbox-c9xaf086-8zxc-4565-9cbc-64e8fc35d0d2"}}'
        )
        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        data_log = {
            "application_id": self.application.id,
            "service_provider": "brick",
            "api_type": "POST",
            "http_status_code": str(result.status_code),
            "query_params": str(result.url),
            "request": "header: " + str(result.headers) + " body: " + str(result.body),
            "response": str(result.json()),
            "error_message": "",
        }
        bpjs = Bpjs(application=self.application, provider="brick")
        bpjs.log_api_call(**data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()

        assert mock.called
        self.assertTrue(is_exists)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_log_condition_success_key_not_match(self, mock):
        """
        Test for scenario success (200 OK) and save it to logging by response.
        """

        response = Response()
        response.status_code = 200
        response.url = "/testing"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = b'{"status":200,' b'"message":"OK"}'
        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        data_log = {
            "application_id": self.application.id,
            "service_provider": "brick",
            "api_type": "POST",
            "http_status_code": str(result.status_code),
            "query_params": str(result.url),
            "request": "header: " + str(result.headers) + " body: " + str(result.body),
            "response": str(result.json()),
            "error_message": "",
        }
        bpjs = Bpjs(application=self.application, provider="brick")
        bpjs.log_api_call(**data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()

        assert mock.called
        self.assertTrue(is_exists)


class TestViewBrickCallback(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.base_url = (
            "/api/bpjs/v2/applications/" + str(self.application.application_xid) + "/brick-callback"
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)

    def test_case_1(self):
        payload_data = [
            {
                "accessToken": "access-sandbox-a2c56a90-d5ac-4636-ag5d-f021d1dc826s",
                "userId": "1234",
            },
            {
                "accessToken": "access-sandbox-02181f91-3945-414s-bf34-f44564e97d4s",
                "userId": "1234",
            },
        ]

        response = self.client.post(self.base_url, data=payload_data, format="json")
        assert response.status_code == 200
        self.assertEqual(response.content, b"OK")

    def test_case_2(self):
        payload_data = []

        response = self.client.post(self.base_url, data=payload_data, format="json")
        assert response.status_code == 400

    def test_case_3(self):
        payload_data = [
            {
                "accessToken": "access-sandbox-a2c56a90-d5ac-4636-ag5d-f021d1dc826s",
                "userId": "1234",
            },
            {
                "accessToken": "access-sandbox-02181f91-3945-414s-bf34-f44564e97d4s",
                "userId": "1234",
            },
        ]
        self.base_url = (
            "/api/bpjs/v2/applications/"
            + str(self.application.application_xid + 1)
            + "/brick-callback"
        )
        response = self.client.post(self.base_url, data=payload_data, format="json")

        assert response.status_code == 400

    def test_case_4(self):
        payload_data = [
            {
                "accessToken": "access-sandbox-a2c56a90-d5ac-4636-ag5d-f021d1dc826s",
                "userId": "1234",
            },
            {
                "accessToken": "access-sandbox-02181f91-3945-414s-bf34-f44564e97d4s",
                "userId": "1234",
            },
        ]

        response = self.client.post(self.base_url, data=payload_data, format="json")
        assert response.status_code == 200
        self.assertEqual(response.content, b"OK")


class TestBpjsAPILogs(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.base_url = "/api/bpjs/v2/logs"

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)

    def test_case_1(self):
        payload_data = {"application_xid": self.application.application_xid}
        response = self.client.post(self.base_url, data=payload_data)

        assert response.data["success"] == True

    def test_case_2(self):
        payload_data = {"application_xid": self.application.application_xid + 11}
        response = self.client.post(self.base_url, data=payload_data)

        assert response.data["success"] == False

    def test_case_3(self):
        payload_data = {}
        response = self.client.post(self.base_url, data=payload_data)
        assert response.data["errors"][0] == "application_xid is empty!"

    def test_case_4(self):
        payload_data = {"application_xid": "asdasd"}
        response = self.client.post(self.base_url, data=payload_data)
        assert response.data["errors"][0] == "application_xid must number!"

    def test_case_5(self):
        payload_data = {
            "application_xid": self.application.application_xid,
            "http_status_code": 409,
        }

        response = self.client.post(self.base_url, data=payload_data)
        result = BpjsAPILog.objects.get(application=self.application)

        result_http_code = result.http_status_code
        assert result_http_code == "409"


class TestGenerateWebViewBrick(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.content_type = "application/json"
        self.base_url = "/api/bpjs/v2/generate-web-view-bpjs"

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        self.application.update_safely(
            application_status_id=100,
            application_xid=8078010691,
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)
        self.payload = {'application_id': self.application.id}

    def generate_widget_url(self, access_token):

        callback_endpoint = BrickSetupClient.JULO_PATH_CALLBACK.format(
            self.application.application_xid
        )
        fullpath_callback = '{0}{1}'.format(
            settings.BASE_URL,
            callback_endpoint,
        )
        widget_url = '{0}/v1/?accessToken={1}&redirect_url={2}'.format(
            BrickSetupClient.BRICK_WIDGET_BASE_URL,
            access_token,
            fullpath_callback,
        )

        return widget_url

    @patch("juloserver.bpjs.clients.requests")
    def test_generate_webview(self, mock_request):

        public_access_token = 'public-sandbox-f1b235dd-5a8b-4555-a9af-78b8cf14d501'
        expect_widget = self.generate_widget_url(public_access_token)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": 200,
            "message": "OK",
            "data": {"access_token": public_access_token},
        }
        mock_request.get.return_value = mock_response

        response = self.client.post(self.base_url, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['widget_url'], expect_widget)

    @patch("juloserver.bpjs.clients.requests")
    def test_generate_webview_bad_request_public_access_token(self, mock_request):

        public_access_token = ''
        expect_widget = self.generate_widget_url(public_access_token)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": 200,
            "message": "OK",
            "data": {"access_token": public_access_token},
        }
        mock_request.get.return_value = mock_response

        response = self.client.post(self.base_url, data=self.payload, format='json')
        self.assertEqual(response.status_code, 400)

    @patch("juloserver.bpjs.clients.requests")
    def test_generate_webview_bad_request_application_xid(self, mock_request):

        public_access_token = 'public-sandbox-f1b235dd-5a8b-4555-a9af-78b8cf14d501'
        expect_widget = self.generate_widget_url(public_access_token)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": 200,
            "message": "OK",
            "data": {"access_token": public_access_token},
        }
        mock_request.get.return_value = mock_response

        self.application.update_safely(application_xid=None)
        response = self.client.post(self.base_url, data=self.payload, format='json')
        self.assertEqual(response.status_code, 400)

    @patch("juloserver.bpjs.clients.requests")
    def test_generate_webview_bad_request_application_id(self, mock_request):
        public_access_token = 'public-sandbox-f1b235dd-5a8b-4555-a9af-78b8cf14d501'
        expect_widget = self.generate_widget_url(public_access_token)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": 200,
            "message": "OK",
            "data": {"access_token": public_access_token},
        }
        mock_request.get.return_value = mock_response

        self.payload['application_id'] = None
        response = self.client.post(self.base_url, data=self.payload, format='json')
        self.assertEqual(response.status_code, 400)
