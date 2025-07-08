import datetime
import logging

import mock
import requests
from django.test.testcases import TestCase
from mock.mock import (
    Mock,
    patch,
)

from juloserver.fraud_score.clients import FinscoreClient
from juloserver.fraud_score.models import (
    FinscoreApiRawResult,
    FinscoreApiResult,
)


class TestFinscoreClient(TestCase):
    def setUp(self):
        self.data = {
            'application_id': 1,
            'apply_time': '2023-11-27 15:55:55',
            'id': '1234567890',
            'phone_number': '0821679123456',
            'fullname': 'Picolo',
            'app_name': 'JuloTek_and',
            'package_id': 'finscore5.1',
            'device_id': 'some-device-id',
        }

    def test_construct_payload(self):
        expected_result = {
            'apply_time': '2023-11-27 15:55:55',
            'id_num': '1234567890',
            'act_mbl': '0821679123456',
            'full_nm': 'Picolo',
            'app_name': 'JuloTek_and',
            'package_id': 'finscore5.1',
            'device_id': 'some-device-id',
        }

        finscore_client = FinscoreClient('partner_code', 'partner_key', 'host_url')
        result = finscore_client.construct_payload(self.data)

        self.assertEqual(result, expected_result)

    def test_construct_payload_no_device_id(self):
        del self.data['device_id']
        expected_result = {
            'apply_time': '2023-11-27 15:55:55',
            'id_num': '1234567890',
            'act_mbl': '0821679123456',
            'full_nm': 'Picolo',
            'app_name': 'JuloTek_and',
            'package_id': 'finscore5.1',
        }

        finscore_client = FinscoreClient('partner_code', 'partner_key', 'host_url')
        result = finscore_client.construct_payload(self.data)

        self.assertEqual(result, expected_result)

    @patch('juloserver.fraud_score.clients.finscore.FinscoreClient.construct_payload')
    @patch('juloserver.fraud_score.clients.finscore.requests')
    def test_fetch_finscore_result_success(self, mock_requests, mock_construct_payload):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'code': 0,
            'data': [
                {
                    'name': 'finscore5.1',
                    'reasonCode': 200,
                    'value': 821.0
                }
            ],
            'message': 'Success.',
        }
        mock_response.elapsed = '00:00:00.123'
        mock_requests.post.return_value = mock_response
        mock_requests.raise_for_status.return_value = None
        mock_construct_payload.return_value = None

        finscore_client = FinscoreClient('partner_code', 'partner_key', 'host_url')
        result, error = finscore_client.fetch_finscore_result(self.data)
        result = result.json()

        self.assertEqual(result['code'], 0)
        self.assertEqual(result['data'][0]['value'], 821.0)
        self.assertEqual(result['message'], 'Success.')

    @patch('juloserver.fraud_score.clients.finscore.requests.post',
        side_effect=requests.exceptions.RequestException())
    @patch('juloserver.fraud_score.clients.finscore.logger')
    def test_fetch_finscore_result_with_request_exception(self, mock_logger, mock_post):
        finscore_client = FinscoreClient('partner_code', 'partner_key', 'host_url')
        result, error = finscore_client.fetch_finscore_result(self.data)

        self.assertEqual(result, None)
        self.assertTrue(error)

        self.assertEqual(FinscoreApiResult.objects.count(), 0)
        self.assertEqual(FinscoreApiRawResult.objects.count(), 0)

        mock_logger.exception.assert_called_once_with({
            'action': 'fetch_finscore_result',
            'message': 'HTTP requests exception detected.',
            'error': mock.ANY,
            'application_id': 1,
        })

    @patch('juloserver.fraud_score.clients.finscore.requests.post',
        side_effect=Exception('Test error'))
    @patch('juloserver.fraud_score.clients.finscore.logger')
    def test_fetch_finscore_with_unexpected_exception(self, mock_logger, mock_post):
        finscore_client = FinscoreClient('partner_code', 'partner_key', 'host_url')
        result, error = finscore_client.fetch_finscore_result(self.data)

        self.assertEqual(result, None)
        self.assertTrue(error)

        self.assertEqual(FinscoreApiResult.objects.count(), 0)
        self.assertEqual(FinscoreApiRawResult.objects.count(), 0)

        mock_logger.exception.assert_called_once_with({
            'action': 'fetch_finscore_result',
            'message': 'Unexpected error during Finscore score retrieval.',
            'error': mock.ANY,
            'application_id': 1,
        })
