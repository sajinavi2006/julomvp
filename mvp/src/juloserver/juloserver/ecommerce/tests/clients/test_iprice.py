import json
from unittest.mock import (
    patch,
    MagicMock,
    call,
)

import responses
from django.test import SimpleTestCase
from requests import HTTPError
from rest_framework.exceptions import ValidationError

from juloserver.ecommerce.clients.iprice import IpriceClient

PACKAGE_NAME = 'juloserver.ecommerce.clients.iprice'


class TestIpriceClientInit(SimpleTestCase):
    def test_init(self):
        client = IpriceClient('http://iprice:8000', 'pid')

        self.assertEqual('http://iprice:8000', client.base_url)
        self.assertEqual('pid', client.pid)


class TestIpriceClientPost(SimpleTestCase):
    def setUp(self):
        self.client = IpriceClient('http://iprice:8000', pid='pid')
        self.response_data = {'status': 'ok'}

    @responses.activate
    @patch('{}.logger'.format(PACKAGE_NAME))
    def test_post_success(self, mock_logger):
        responses.add(
            'POST',
            url='http://iprice:8000/path',
            status=200,
            json=self.response_data,
            match=[
                responses.matchers.json_params_matcher({'data': 'data'}),
                responses.matchers.header_matcher({'Header': 'header'}),
            ]
        )

        response = self.client.post('/path', json={'data': 'data'}, headers={'Header': 'header'})
        self.assertEqual(self.response_data, response)
        mock_logger.info.assert_has_calls([
            call({
                'action': 'juloserver.loan.clients.iprice.iPriceClient.post',
                'message': 'sending request to iPrice',
                'retries': 0,
                'request_url': 'http://iprice:8000/path',
                'request_json': {'data': 'data'},
                'request_params': None,
            }),
            call({
                'action': 'juloserver.loan.clients.iprice.iPriceClient.post',
                'message': 'iprice request success',
                'retries': 0,
                'request_url': 'http://iprice:8000/path',
                'request_json': {'data': 'data'},
                'request_params': None,
                'response_status': 200,
                'response_body': json.dumps(self.response_data),
            }),
        ])

    @responses.activate
    @patch('{}.sleep'.format(PACKAGE_NAME))
    @patch('{}.logger'.format(PACKAGE_NAME))
    def test_post_500(self, mock_logger, mock_sleep):
        responses.add(
            'POST',
            url='http://iprice:8000/path',
            status=500,
            json={'status': 'error'},
            match=[
                responses.matchers.json_params_matcher({'data': 'data'}),
                responses.matchers.header_matcher({'Header': 'header'}),
            ]
        )

        with self.assertRaises(HTTPError):
            self.client.post('/path', json={'data': 'data'}, headers={'Header': 'header'},
                             params={'params': 'params'}, retries=2)

        logger_calls = [call({
            'action': 'juloserver.loan.clients.iprice.iPriceClient.post',
            'retries': i,
            'request_url': 'http://iprice:8000/path',
            'request_json': {'data': 'data'},
            'request_params': {'params': 'params'},
            'response_status': 500,
            'response_body': json.dumps({'status': 'error'}),
            'message': 'Retrying iPrice post request...',
        }) for i in range(3)]
        mock_logger.warning.assert_has_calls(logger_calls)

    @responses.activate
    @patch('{}.sleep'.format(PACKAGE_NAME))
    @patch('{}.logger'.format(PACKAGE_NAME))
    def test_post_400(self, mock_logger, mock_sleep):
        responses.add(
            'POST',
            url='http://iprice:8000/path',
            status=400,
            json={'status': 'error'},
            match=[
                responses.matchers.json_params_matcher({'data': 'data'}),
                responses.matchers.header_matcher({'Header': 'header'}),
            ]
        )

        with self.assertRaises(HTTPError):
            self.client.post('/path', json={'data': 'data'}, headers={'Header': 'header'})

        mock_logger.error.assert_called_once_with({
            'action': 'juloserver.loan.clients.iprice.iPriceClient.post',
            'retries': 0,
            'request_url': 'http://iprice:8000/path',
            'request_json': {'data': 'data'},
            'request_params': None,
            'response_status': 400,
            'response_body': json.dumps({'status': 'error'}),
            'message': 'Request failed.',
        })


class TestIpricePostInvoiceCallback(SimpleTestCase):
    def setUp(self):
        self.client = IpriceClient('http://iprice:8000', pid='pid')
        self.success_post_data = {
            'iprice_order_id': 'b113650m',
            'application_id': 123456678902,
            'loan_id': 123456678902,
            'transaction_id': '0df9fe3e-c7d2-44cd-8f02-da999ca2a6d8',
            'transaction_status': 'processing',
        }
        self.success_response_data = {
            'orderId': 'b113650m',
            'applicationId': '123456678902',
            'confirmationStatus': 'success',
        }
        self.mock_post = MagicMock()
        self.client.post = self.mock_post

    def test_success(self):
        self.mock_post.return_value = self.success_response_data

        ret_val = self.client.post_invoice_callback(data=self.success_post_data)

        self.assertEqual({
            'order_id': 'b113650m',
            'application_id': '123456678902',
            'confirmation_status': 'success'
        }, ret_val)
        self.mock_post.assert_called_once_with(
            '/v1/invoice-callback/julo',
            json=self.success_post_data,
            params={'pid': 'pid'},
            retries=2
        )

    @patch('{}.logger'.format(PACKAGE_NAME))
    def test_invalid_response(self, mock_logger):
        self.mock_post.return_value = {'invalid': 'data'}

        with self.assertRaises(ValidationError):
            self.client.post_invoice_callback(data=self.success_post_data)

        self.mock_post.assert_called_once_with(
            '/v1/invoice-callback/julo',
            json=self.success_post_data,
            params={'pid': 'pid'},
            retries=2
        )
        mock_logger.warning.assert_called_once_with({
            'action': 'juloserver.loan.clients.iprice.iPriceClient.post_invoice_callback',
            'message': 'iPrice response validation error',
            'error': {'order_id': ['This field is required.'], 'confirmation_status': ['This field is required.']},
            'request_data': self.success_post_data,
            'response_data': {'invalid': 'data'},
        })

    @patch('{}.logger'.format(PACKAGE_NAME))
    def test_invalid_response_none(self, mock_logger):
        self.mock_post.return_value = None

        with self.assertRaises(ValidationError):
            self.client.post_invoice_callback(data=self.success_post_data)

        self.mock_post.assert_called_once_with(
            '/v1/invoice-callback/julo',
            json=self.success_post_data,
            params={'pid': 'pid'},
            retries=2
        )
        mock_logger.warning.assert_called_once_with({
            'action': 'juloserver.loan.clients.iprice.iPriceClient.post_invoice_callback',
            'message': 'iPrice response validation error',
            'error': {'order_id': ['This field is required.'], 'confirmation_status': ['This field is required.']},
            'request_data': self.success_post_data,
            'response_data': None,
        })
