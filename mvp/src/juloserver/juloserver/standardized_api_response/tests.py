from collections import namedtuple
from django.test import TestCase
from django.http import QueryDict
from mock import patch, MagicMock

from juloserver.standardized_api_response.mixin import LoggingHandler

http_request = namedtuple('http_request', ('META', 'method', 'GET', 'data', 'FILES', 'path'))
http_response = namedtuple('http_response', ('data',))


class TestLoggingHandler(TestCase):

    def setUp(self) -> None:
        pass

    @patch('juloserver.standardized_api_response.mixin.get_client_ip_from_request')
    def test_log_request(self, mock_get_client_ip_from_request):
        q_dict = QueryDict('', mutable=True)
        q_dict.update({'param1': {'param1.1': 'value1'}, 'param2': 'value2'})
        META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
        }
        request = http_request(
            META, 'POST', MagicMock(), q_dict, None, 'test_path')
        logging_data_conf = {
            'log_data': ['request'],
            'exclude_fields': {'request': (('param1', 'param1.1'),)},
            'log_success_response': True  # if you want to log data for status < 400
        }
        mock_get_client_ip_from_request.return_value = '127.0.0.1'
        handler = LoggingHandler(logging_data_conf, request)
        handler.parse_request()
        new_q_dict = QueryDict('', mutable=True)
        new_q_dict.update({'param1': {'param1.1': '******'}, 'param2': 'value2'})
        self.assertEqual(new_q_dict, handler.log_content['request_body'])

    @patch('juloserver.standardized_api_response.mixin.get_client_ip_from_request')
    def test_log_response(self, mock_get_client_ip_from_request):
        q_dict = QueryDict('', mutable=True)
        q_dict.update({'param1': {'param1.1': 'value1'}, 'param2': 'value2'})
        META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
        }
        request = http_request(
            META, 'POST', MagicMock(), q_dict, None, 'test_path')
        logging_data_conf = {
            'log_data': ['request'],
            'exclude_fields': {'request': (('param1', 'param1.1'),)},
            'log_success_response': True  # if you want to log data for status < 400
        }
        mock_get_client_ip_from_request.return_value = '127.0.0.1'
        handler = LoggingHandler(logging_data_conf, request)
        handler.parse_response(response=http_response({'success': ' True'}))
        self.assertEqual(handler.log_content['response_body'], {'success': ' True'})

    @patch('juloserver.standardized_api_response.mixin.get_client_ip_from_request')
    def test_log_header(self, mock_get_client_ip_from_request):
        q_dict = QueryDict('', mutable=True)
        q_dict.update({'param1': {'param1.1': 'value1'}, 'param2': 'value2'})
        META = {
            'HTTP_X_FORWARDED_FOR': '127.0.0.1',
            'CONTENT_TYPE': 'application/json',
            'HTTP_AUTHORIZATION': 'Token 97330addf5305740aeab7632ad99254bf396583c',
        }
        request = http_request(
            META, 'POST', MagicMock(), q_dict, None, 'test_path')
        logging_data_conf = {
            'log_data': ['header'],
            'header_prefix': 'HTTP',
            'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
            'log_success_response': True  # if you want to log data for status < 400
        }
        mock_get_client_ip_from_request.return_value = '127.0.0.1'
        handler = LoggingHandler(logging_data_conf, request)
        handler.parse_headers()
        self.assertEqual(
            handler.log_content['header_data'],
            {'HTTP_X_FORWARDED_FOR': '127.0.0.1', 'HTTP_AUTHORIZATION': '******'}
        )
