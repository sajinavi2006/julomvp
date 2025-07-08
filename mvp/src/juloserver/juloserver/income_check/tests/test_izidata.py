import datetime
from datetime import timedelta
from io import StringIO

import mock
from django.conf import settings
from django.core.management import call_command
from django.test.testcases import TestCase
from mock import patch
from requests.models import Response
from rest_framework.test import APIClient, APITestCase

from juloserver.income_check.services import check_salary_izi_data
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    CreditScoreFactory,
)


class TestCheckSalaryIziData(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.credit_score = CreditScoreFactory(application_id=self.application.id)

    @patch('juloserver.income_check.services.request_izi_data')
    def test_check_salary_izi_data_success(self, mock_client):
        response = Response()
        response.status_code = 200
        response._content = b'{ "status" : "OK" }'
        response.elapsed = datetime.timedelta(seconds=2.0)

        mock_response = {
            'headers': '',
            'response': response,
            'url': 'salary',
        }
        mock_client.return_value = mock_response

        result = check_salary_izi_data(self.application)

        assert mock_client.called
        assert result == True

    @patch('juloserver.income_check.services.request_izi_data')
    def test_check_salary_izi_data_invalid_id_number(self, mock_client):
        response = Response()
        response.status_code = 200
        response._content = b'{ "status" : "INVALID_ID_NUMBER" }'
        response.elapsed = datetime.timedelta(seconds=2.0)

        mock_response = {
            'headers': '',
            'response': response,
            'url': 'salary',
        }
        mock_client.return_value = mock_response

        result = check_salary_izi_data(self.application)

        assert mock_client.called
        assert result == False

    @patch('juloserver.income_check.services.request_izi_data')
    def test_check_salary_izi_data_person_not_found(self, mock_client):
        response = Response()
        response.status_code = 200
        response._content = b'{ "status" : "PERSON_NOT_FOUND" }'
        response.elapsed = datetime.timedelta(seconds=2.0)

        mock_response = {
            'headers': '',
            'response': response,
            'url': 'salary',
        }
        mock_client.return_value = mock_response

        result = check_salary_izi_data(self.application)

        assert mock_client.called
        assert result == False

    @patch('juloserver.income_check.services.request_izi_data')
    def test_check_salary_izi_data_retry_later(self, mock_client):
        response = Response()
        response.status_code = 200
        response._content = b'{ "status" : "RETRY_LATER" }'
        response.elapsed = datetime.timedelta(seconds=2.0)

        mock_response = {
            'headers': '',
            'response': response,
            'url': 'salary',
        }
        mock_client.return_value = mock_response

        result = check_salary_izi_data(self.application)

        assert mock_client.called
        assert result == False
