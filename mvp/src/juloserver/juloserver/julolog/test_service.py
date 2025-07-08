import logging
import json

from django.test import TestCase
from mock import patch, mock

from juloserver.julolog.julolog import JuloLog

julolog = JuloLog(__name__)
logger = logging.getLogger(__name__)


class TestFuncJuloLog(TestCase):

    def setUp(self):

        self.action = "juloserver.julolog.test_service"

    @patch('logging.Logger.info')
    def test_log_for_case_info(self, mock):

        self.level = "INFO"
        self.message = "test"
        basic_dict = {
            "action": self.action,
            "level": self.level,
            "message": self.message,
            "url": None,
            "ip_address": None,
            "func_name": "test_log_for_case_info",
        }

        expected_result = json.dumps(basic_dict)
        julolog.info(message=self.message)
        mock.assert_called_with(expected_result)

    @patch('logging.Logger.warning')
    def test_log_for_case_warning(self, mock):
        self.level = "WARNING"
        self.message = "Testing flow 2"
        basic_dict = {
            "action": self.action,
            "level": self.level,
            "message": self.message,
            "url": None,
            "ip_address": None,
            "func_name": "test_log_for_case_warning",
        }

        expected_result = json.dumps(basic_dict)
        julolog.warning(message=self.message)
        mock.assert_called_with(expected_result)

    @patch('logging.Logger.debug')
    def test_log_for_case_extra(self, mock):
        self.level = "DEBUG"
        self.message = "Testing flow 3"
        log_data = {"application": 12313131231}
        basic_dict = {
            "action": self.action,
            "level": self.level,
            "message": self.message,
            "url": None,
            "ip_address": None,
            "func_name": "test_log_for_case_extra",
        }

        full_dict = {**basic_dict, **log_data}
        expected_result = json.dumps(full_dict)
        julolog.debug(message=log_data)
        mock.assert_called_with(expected_result)

    @patch('logging.Logger.error')
    def test_log_for_case_empty_message_and_error_level(self, mock):
        self.level = "ERROR"
        self.message = None

        basic_dict = {
            "action": self.action,
            "level": self.level,
            "message": self.message,
            "url": None,
            "ip_address": None,
            "func_name": "test_log_for_case_empty_message_and_error_level",
        }

        expected_result = json.dumps(basic_dict)
        julolog.error(message=self.message)
        mock.assert_called_with(expected_result)

    @patch('logging.Logger.critical')
    def test_log_for_case_extra(self, mock):
        self.level = "CRITICAL"
        self.message = "Testing flow critical"
        log_data = {"application": 12313131231, "message": self.message}
        basic_dict = {
            "action": self.action,
            "level": self.level,
            "message": self.message,
            "url": None,
            "ip_address": None,
            "func_name": "test_log_for_case_extra",
        }

        full_dict = {**basic_dict, **log_data}
        expected_result = json.dumps(full_dict)
        julolog.critical(message=log_data)
        mock.assert_called_with(expected_result)
