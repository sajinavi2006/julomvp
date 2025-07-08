import json

from mock import patch
from http import HTTPStatus
from requests.models import Response

from django.test import TestCase

from juloserver.grab.clients.clients import GrabClient, GrabPaths
from juloserver.grab.tests.factories import (
    GrabAPILogFactory,
    GrabCustomerDataFactory
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory
)
from juloserver.grab.models import (
    GrabAPILog
)


class TestGrabClient(TestCase):
    def setUp(self):
        self.dummy_response = {"message": "hello world"}
        self.customer = CustomerFactory()
        GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)

    def test_construct_response_from_log(self):
        api_log = GrabAPILogFactory(
            http_status_code=HTTPStatus.OK,
            response=json.dumps(self.dummy_response)
        )
        response = GrabClient.construct_response_from_log(api_log)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.dummy_response)

    def test_construct_response_from_log_non_json(self):
        api_log = GrabAPILogFactory(
            http_status_code=HTTPStatus.OK,
            response="testing"
        )
        response = GrabClient.construct_response_from_log(api_log)
        self.assertEqual(response.status_code, 200)
        with self.assertRaises(json.JSONDecodeError):
            response.json()

    def test_fetch_application_submission_log_no_application_data_log(self):
        GrabAPILogFactory(
            customer_id=self.customer.id,
            application_id=self.application.id,
            http_status_code=HTTPStatus.OK,
            query_params=GrabPaths.APPLICATION_CREATION,
            response=json.dumps(self.dummy_response)
        )
        response = GrabClient.fetch_application_submission_log(
            self.application.id,
            self.customer.id
        )
        self.assertEqual(response.json(), self.dummy_response)

    def test_fetch_application_submission_log_no_application_data_log(self):
        GrabAPILogFactory(
            customer_id=self.customer.id,
            application_id=self.application.id,
            http_status_code=HTTPStatus.OK,
            response=json.dumps(self.dummy_response)
        )
        response = GrabClient.fetch_application_submission_log(
            self.application.id,
            self.customer.id
        )
        self.assertEqual(response, None)

    def test_fetch_application_submission_log_no_log(self):
        response = GrabClient.fetch_application_submission_log(
            self.application.id,
            self.customer.id
        )
        self.assertEqual(response, None)

    @patch("requests.post")
    def test_submit_application_creation(self, mock_post):
        response = Response()
        response.status_code = HTTPStatus.OK
        response.headers = {"Content": "application/json"}
        response._content = json.dumps({"message": "hello there"}).encode("utf-8")
        mock_post.return_value = response

        resp = GrabClient.submit_application_creation(
            application_id=self.application.id,
            customer_id=self.customer.id
        )
        self.assertEqual(resp.status_code, HTTPStatus.OK)
        self.assertEqual(resp.json(), {"message": "hello there"})
        api_log = GrabAPILog.objects.filter(
            application_id=self.application.id,
            customer_id=self.customer.id,
            query_params__contains='applicationData'
        )
        self.assertTrue(api_log.exists())
        self.assertEqual(api_log.last().http_status_code, HTTPStatus.OK)

    @patch("requests.post")
    def test_submit_application_creation_409(self, mock_post):
        response = Response()
        response.status_code = HTTPStatus.CONFLICT
        response.headers = {"Content": "application/json"}
        response._content = json.dumps({"message": "hello there"}).encode("utf-8")
        mock_post.return_value = response

        resp = GrabClient.submit_application_creation(
            application_id=self.application.id,
            customer_id=self.customer.id
        )
        self.assertEqual(resp.status_code, HTTPStatus.CONFLICT)
        self.assertEqual(resp.json(), {"message": "hello there"})
        api_log = GrabAPILog.objects.filter(
            application_id=self.application.id,
            customer_id=self.customer.id,
            query_params__contains='applicationData'
        )
        self.assertTrue(api_log.exists())
        self.assertEqual(api_log.last().http_status_code, HTTPStatus.CONFLICT)

    @patch("requests.post")
    def test_submit_application_creation_409_application_exists(self, mock_post):
        response = Response()
        response.status_code = HTTPStatus.CONFLICT
        response.headers = {"Content": "application/json"}
        content = {
            "msg_id": "ca0c3bf4891f4349bf76a5ac79175277",
            "success": False,
            "error": {
                "code": "4021",
                "message": "ErrorApplicationAlreadyExists"
            }
        }
        response._content = json.dumps(content).encode("utf-8")
        mock_post.return_value = response

        resp = GrabClient.submit_application_creation(
            application_id=self.application.id,
            customer_id=self.customer.id
        )
        self.assertEqual(resp.status_code, HTTPStatus.OK)
        self.assertEqual(resp.json(), content)
        api_log = GrabAPILog.objects.filter(
            application_id=self.application.id,
            customer_id=self.customer.id,
            query_params__contains='applicationData'
        )
        self.assertTrue(api_log.exists())
        self.assertEqual(api_log.last().http_status_code, HTTPStatus.OK)

    @patch("requests.post")
    def test_submit_application_creation_409_application_exists_with_newline(self, mock_post):
        response = Response()
        response.status_code = HTTPStatus.CONFLICT
        response.headers = {"Content": "application/json"}
        content = '''
        {
            "msg_id": "ca0c3bf4891f4349bf76a5ac79175277", "success": false,
            "error": {
                "code": "4021",
                "message": "ErrorApplicationAlreadyExists"
            }
        }
        '''
        response._content = json.dumps(content).encode("utf-8")
        mock_post.return_value = response

        resp = GrabClient.submit_application_creation(
            application_id=self.application.id,
            customer_id=self.customer.id
        )
        self.assertEqual(resp.status_code, HTTPStatus.OK)
        self.assertEqual(resp.json(), content)
        api_log = GrabAPILog.objects.filter(
            application_id=self.application.id,
            customer_id=self.customer.id,
            query_params__contains='applicationData'
        )
        self.assertTrue(api_log.exists())
        self.assertEqual(api_log.last().http_status_code, HTTPStatus.OK)
