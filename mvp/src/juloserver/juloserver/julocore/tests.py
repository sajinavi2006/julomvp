from builtins import range
from decimal import Decimal
from django.test.client import RequestFactory

import mock
from django.db.transaction import get_connection
from django.test.testcases import TestCase, SimpleTestCase
from django.test import override_settings

from juloserver.julocore.python2.utils import py2round
from juloserver.julocore.restapi.middleware import ApiLoggingMiddleware
from django.http import QueryDict
from juloserver.julocore.utils import get_client_ip


def force_run_on_commit_hook():
    try:
        while get_connection().run_on_commit:
            try:
                sids, func = get_connection().run_on_commit.pop(0)
                func()
            except IndexError:
                # This catches the case where the list becomes empty before pop(0) can be executed.
                break  # Exit the loop if there are no more items to pop.
    finally:
        get_connection().run_on_commit = []


class TestPython2Utils(TestCase):
    def test_py2round_invalid(self):
        with self.assertRaises(TypeError) as context:
            py2round('asdf', 'asdf')

        with self.assertRaises(TypeError) as context:
            py2round(1, 'test')

        with self.assertRaises(TypeError) as context:
            py2round('test', 1)

        with self.assertRaises(TypeError) as context:
            py2round('test', 1.01)

        with self.assertRaises(TypeError) as context:
            py2round(Decimal(1.01), Decimal(1.01))

        with self.assertRaises(TypeError) as context:
            py2round(Decimal(1.01), 2)

    def test_py2round(self):
        data_input = [x / 10.0 for x in range(1, 10)]
        expected_output = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0]

        output = [py2round(x) for x in data_input]
        assert expected_output == output
        # ---
        data_input = [x / 100.0 for x in range(1, 10)]
        expected_output = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09]
        digit = 2

        output = [py2round(x, digit) for x in data_input]
        assert expected_output == output
        # ---
        data_input = list(range(1000, 10000, 500))
        digit = -3
        expected_output = [
            1000.0,
            2000.0,
            2000.0,
            3000.0,
            3000.0,
            4000.0,
            4000.0,
            5000.0,
            5000.0,
            6000.0,
            6000.0,
            7000.0,
            7000.0,
            8000.0,
            8000.0,
            9000.0,
            9000.0,
            10000.0,
        ]

        output = [py2round(x, digit) for x in data_input]
        assert expected_output == output
        # ---
        data_input = [x / 1000.0 for x in range(1, 10)]
        digit = 2
        expected_output = [0.0, 0.0, 0.0, 0.0, 0.01, 0.01, 0.01, 0.01, 0.01]

        output = [py2round(x, digit) for x in data_input]
        assert expected_output == output


@override_settings(LOGGING_BLACKLISTED_PATHS=["/blacklisted_path"])
class TestApiLoggingMiddleware(TestCase):
    def setUp(self):
        self.middleware = ApiLoggingMiddleware()
        self.request = mock.MagicMock()
        self.request.path = '/path'
        self.request.META = {
            'REMOTE_ADDR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
            'HTTP_USER_AGENT': 'PostmanRuntime/7.26.8',
            'HTTP_ACCEPT': '*/*',
            'HTTP_HOST': 'localhost:8000',
            'HTTP_ACCEPT_ENCODING': 'gzip, deflate, br',
            'HTTP_CONNECTION': 'keep-alive',
            'HTTP_COOKIE': 'csrftoken=561VKw3NlxeWCWmRr32lhPZcardWn4SC',
            'CSRF_COOKIE': '561VKw3NlxeWCWmRr32lhPZcardWn4SC',
        }
        self.request.method = 'POST'
        self.response = mock.MagicMock()
        self.response.status_code = 200

    @mock.patch('juloserver.julocore.restapi.middleware.json.dumps')
    def test_api_error_logging(self, mocked_json):
        mocked_json.return_value = None
        self.middleware.process_request(self.request)
        response = self.middleware.process_response(self.request, self.response)
        self.assertEqual(response, self.response)

        self.response.status_code = 400
        response = self.middleware.process_response(self.request, self.response)
        self.assertEqual(response, self.response)
        mocked_json.assert_called_once()

    @mock.patch('juloserver.julocore.restapi.middleware.round')
    @mock.patch('juloserver.julocore.restapi.middleware.json.dumps')
    def test_ip_address_scenario(self, mocked_json, mocked_round):
        mocked_round.return_value = 0.002
        ip_log = {
            'action': 'logging_api_error',
            'ip_address': '127.0.0.1',
            'method': 'POST',
            'path': '/path',
            'request_params': self.request.GET.dict(),
            'request_body': self.request.POST.dict(),
            'payload_size': 0,
            'response_status': 400,
            'response_body': self.response.content.decode(),
            'duration': 0.002,
        }

        mocked_json.return_value = None
        self.response.status_code = 400
        response = self.middleware.process_response(self.request, self.response)
        self.assertEqual(response, self.response)
        mocked_json.assert_called_once()
        mocked_json.assert_called_with(ip_log)

        mocked_json.reset_mock()

        self.request.META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
            'HTTP_USER_AGENT': 'PostmanRuntime/7.26.8',
            'HTTP_ACCEPT': '*/*',
            'HTTP_HOST': 'localhost:8000',
            'HTTP_ACCEPT_ENCODING': 'gzip, deflate, br',
            'HTTP_CONNECTION': 'keep-alive',
            'HTTP_COOKIE': 'csrftoken=561VKw3NlxeWCWmRr32lhPZcardWn4SC',
            'CSRF_COOKIE': '561VKw3NlxeWCWmRr32lhPZcardWn4SC',
        }
        self.response.status_code = 400
        response = self.middleware.process_response(self.request, self.response)
        self.assertEqual(response, self.response)
        mocked_json.assert_called_once()
        mocked_json.assert_called_with(ip_log)

        mocked_json.reset_mock()

        self.request.META = {
            'HTTP_X_REAL_IP': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
            'HTTP_USER_AGENT': 'PostmanRuntime/7.26.8',
            'HTTP_ACCEPT': '*/*',
            'HTTP_HOST': 'localhost:8000',
            'HTTP_ACCEPT_ENCODING': 'gzip, deflate, br',
            'HTTP_CONNECTION': 'keep-alive',
            'HTTP_COOKIE': 'csrftoken=561VKw3NlxeWCWmRr32lhPZcardWn4SC',
            'CSRF_COOKIE': '561VKw3NlxeWCWmRr32lhPZcardWn4SC',
        }
        self.response.status_code = 400
        response = self.middleware.process_response(self.request, self.response)
        self.assertEqual(response, self.response)
        mocked_json.assert_called_once()
        mocked_json.assert_called_with(ip_log)

    @mock.patch('juloserver.julocore.restapi.middleware.round')
    @mock.patch('juloserver.julocore.restapi.middleware.json.dumps')
    def test_form_data(self, mocked_dumps, mocked_round):
        mocked_round.return_value = 0.002
        ip_log = {
            'action': 'logging_api_error',
            'ip_address': '127.0.0.1',
            'method': 'POST',
            'path': '/path',
            'request_params': {'phone_number': '62811027376454'},
            'request_body': {
                'phone_number': '62811027376454',
                'program_id': 'DAX_ID_CL02',
                'loan_amount': 500000,
                'interest_rate': 5,
                'upfront_fee': 20000,
                'min_tenure': 60,
                'tenure': 60,
                'tenure_interval': 10,
                'offer_threshold': 500000,
            },
            'payload_size': 0,
            'response_status': 400,
            'response_body': '{"success":false,"data":null,"errors":["Unauthorized request"]}',
            'duration': 0.002,
        }

        self.request.META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
            'HTTP_USER_AGENT': 'PostmanRuntime/7.26.8',
            'HTTP_ACCEPT': '*/*',
            'HTTP_HOST': 'localhost:8000',
            'HTTP_ACCEPT_ENCODING': 'gzip, deflate, br',
            'HTTP_CONNECTION': 'keep-alive',
            'HTTP_COOKIE': 'csrftoken=561VKw3NlxeWCWmRr32lhPZcardWn4SC',
            'CSRF_COOKIE': '561VKw3NlxeWCWmRr32lhPZcardWn4SC',
        }
        self.request.method = 'POST'
        self.request.POST = None
        get_params = QueryDict('', mutable=True)
        get_params.update({"phone_number": "62811027376454"})
        self.request.GET = get_params
        self.request.body = (
            b'{\n    "phone_number": "62811027376454",\n    "program_id": "DAX_ID_CL02",\n    '
            b'"loan_amount": 500000,\n    "interest_rate": 5,\n    "upfront_fee": 20000,\n    '
            b'"min_tenure": 60,\n    "tenure": 60,\n    "tenure_interval": 10,\n    '
            b'"offer_threshold": 500000\n}'
        )
        self.response.status_code = 400
        self.response.content = b'{"success":false,"data":null,"errors":["Unauthorized request"]}'
        ip_log['payload_size'] = len(self.response.content)
        response = self.middleware.process_response(self.request, self.response)
        mocked_dumps.assert_called_with(ip_log)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response, self.response)

    @mock.patch('juloserver.julocore.restapi.middleware.round')
    @mock.patch('juloserver.julocore.restapi.middleware.json.dumps')
    def test_raw_json(self, mocked_dumps, mocked_round):
        mocked_round.return_value = 0.002
        ip_log = {
            'action': 'logging_api_error',
            'ip_address': '127.0.0.1',
            'method': 'POST',
            'path': '/api/loan/v2/loan/',
            'request_params': {},
            'request_body': {
                'transaction_type_code': 9,
                'loan_amount_request': 0,
                'account_id': 1433,
                'loan_duration': 1,
                'pin': '159357',
                'self_bank_account': False,
                'is_payment_point': False,
                'bpjs_times': 0,
                'qr_id': 148,
            },
            'payload_size': 0,
            'response_status': 401,
            'response_body': '{"success":false,"data":null,"errors":["Unauthorized request"]}',
            'duration': 0.002,
        }
        self.request.path = '/api/loan/v2/loan/'
        self.request.META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
            'HTTP_USER_AGENT': 'PostmanRuntime/7.26.8',
            'HTTP_ACCEPT': '*/*',
            'HTTP_HOST': 'localhost:8000',
            'HTTP_ACCEPT_ENCODING': 'gzip, deflate, br',
            'HTTP_CONNECTION': 'keep-alive',
            'HTTP_COOKIE': 'csrftoken=561VKw3NlxeWCWmRr32lhPZcardWn4SC',
            'CSRF_COOKIE': '561VKw3NlxeWCWmRr32lhPZcardWn4SC',
        }
        self.request.method = 'POST'
        self.request.POST = None
        get_params = QueryDict('', mutable=True)
        get_params.update({})
        self.request.GET = get_params
        self.request.body = (
            b'{\n        "transaction_type_code": 9,\n        '
            b'"loan_amount_request": 0,\n        "account_id": 1433,\n'
            b'        "loan_duration": 1,\n        "pin": "159357",\n '
            b'       "self_bank_account":false,\n        '
            b'"is_payment_point": false,\n        "bpjs_times":0,\n    '
            b'    "qr_id":148\n}'
        )
        self.response.status_code = 401
        self.response.content = b'{"success":false,"data":null,"errors":["Unauthorized request"]}'
        ip_log['payload_size'] = len(self.response.content)
        response = self.middleware.process_response(self.request, self.response)
        mocked_dumps.assert_called_with(ip_log)
        self.assertEqual(response.status_code, 401)

        self.request.body = None
        post_params = QueryDict('', mutable=True)
        post_params.update(
            {
                "transaction_type_code": 9,
                "loan_amount_request": 0,
                "account_id": 1433,
                "loan_duration": 1,
                "pin": "159357",
                "self_bank_account": False,
                "is_payment_point": False,
                "bpjs_times": 0,
                "qr_id": 148,
            }
        )
        self.request.POST = post_params
        response = self.middleware.process_response(self.request, self.response)
        mocked_dumps.assert_called_with(ip_log)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response, self.response)

    @mock.patch('juloserver.julocore.restapi.middleware.round')
    @mock.patch('juloserver.julocore.restapi.middleware.json.dumps')
    def test_blacklisted_api(self, mocked_dumps, mocked_round):
        mocked_round.return_value = 0.002
        ip_log = {
            'action': 'logging_api_error',
            'ip_address': '127.0.0.1',
            'method': 'POST',
            'path': '/blacklisted_path',
            'payload_size': 0,
            'response_status': 401,
            'response_body': '{"success":false,"data":null,"errors":["Unauthorized request"]}',
            'duration': 0.002,
        }
        self.request.path = '/blacklisted_path'
        self.request.META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
            'HTTP_USER_AGENT': 'PostmanRuntime/7.26.8',
            'HTTP_ACCEPT': '*/*',
            'HTTP_HOST': 'localhost:8000',
            'HTTP_ACCEPT_ENCODING': 'gzip, deflate, br',
            'HTTP_CONNECTION': 'keep-alive',
            'HTTP_COOKIE': 'csrftoken=561VKw3NlxeWCWmRr32lhPZcardWn4SC',
            'CSRF_COOKIE': '561VKw3NlxeWCWmRr32lhPZcardWn4SC',
        }
        self.request.method = 'POST'
        self.request.POST = None
        get_params = QueryDict('', mutable=True)
        get_params.update({})
        self.request.GET = get_params
        self.request.body = (
            b'{\n        "transaction_type_code": 9,\n        '
            b'"loan_amount_request": 0,\n        "account_id": 1433,\n'
            b'        "loan_duration": 1,\n        "pin": "159357",\n '
            b'       "self_bank_account":false,\n        '
            b'"is_payment_point": false,\n        "bpjs_times":0,\n    '
            b'    "qr_id":148\n}'
        )
        self.response.status_code = 401
        self.response.content = b'{"success":false,"data":null,"errors":["Unauthorized request"]}'
        ip_log['payload_size'] = len(self.response.content)
        response = self.middleware.process_response(self.request, self.response)
        mocked_dumps.assert_called_with(ip_log)
        self.assertEqual(response.status_code, 401)

        self.request.body = None
        post_params = QueryDict('', mutable=True)
        post_params.update(
            {
                "transaction_type_code": 9,
                "loan_amount_request": 0,
                "account_id": 1433,
                "loan_duration": 1,
                "pin": "159357",
                "self_bank_account": False,
                "is_payment_point": False,
                "bpjs_times": 0,
                "qr_id": 148,
            }
        )
        self.request.POST = post_params
        response = self.middleware.process_response(self.request, self.response)
        mocked_dumps.assert_called_with(ip_log)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response, self.response)


class TestGetClientIP(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_using_http_x_forward_for(self):
        # Multiple IP Address
        request = self.request_factory.get(
            '/',
            HTTP_X_FORWARDED_FOR='127.0.0.1,127.0.0.3',
            REMOTE_ADDR='127.0.0.2',
        )

        ret_val = get_client_ip(request)
        self.assertEqual('127.0.0.1', ret_val)

        # Only one IP address
        request = self.request_factory.get(
            '/',
            HTTP_X_FORWARDED_FOR='127.0.0.1',
            REMOTE_ADDR='127.0.0.2',
        )

        ret_val = get_client_ip(request)
        self.assertEqual('127.0.0.1', ret_val)

    def test_using_assert_remote_addr(self):
        request = self.request_factory.get(
            '/',
            REMOTE_ADDR='127.0.0.2',
        )

        ret_val = get_client_ip(request)
        self.assertEqual('127.0.0.2', ret_val)

    def test_using_assert_x_real_ip(self):
        request = self.request_factory.get(
            '/',
            HTTP_X_FORWARDED_FOR='127.0.0.1',
            REMOTE_ADDR='127.0.0.2',
            HTTP_X_REAL_IP='127.0.0.3',
        )

        ret_val = get_client_ip(request)
        self.assertEqual('127.0.0.3', ret_val)
