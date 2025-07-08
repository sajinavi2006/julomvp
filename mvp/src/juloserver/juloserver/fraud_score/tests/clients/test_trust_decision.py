import datetime
import mock
import requests
from django.test.testcases import TestCase
from django.utils import timezone
from mock.mock import (
    Mock,
    patch,
)

from juloserver.fraud_score.clients.trust_decision import (
    TrustDecisionClient,
    TrustDecisionPayload,
)
from juloserver.fraud_score.models import (
    TrustGuardApiRawResult,
    TrustGuardApiResult,
)


class TestDecisionPayload(TestCase):
    def setUp(self):
        self.test_data = {
            'application_id': 1,
            'fullname': 'Edward',
            'nik': '123123123',
            'event_time': '2022-05-01T12:00:00.000+07:00',
            'black_box': 'testing-black-box-string',
            'ip': '127.0.0.1',
            'phone_number': '62822212223',
            'bank_name': 'BCA',
            'address_province': None,
            'address_regency': None,
            'address_subdistrict': None,
            'address_zip_code': None,
            'event_type': 'LOGIN',
            'customer_id': 3
        }

    def test_construct_event_type(self):
        event_types = ['APPLICATION', 'LOGIN', 'TRANSACTION', 'OPEN_APP']
        expected_results = ['register', 'login', 'loan', 'login']
        for i, event_type in enumerate(event_types):
            test_data = {
                'event_type': event_type
            }
            client = TrustDecisionPayload(test_data)
            result = client._construct_event_type()
            expected_result = expected_results[i]
            self.assertEqual(result, expected_result)

    def test_construct_terminal_data_object(self):
        client = TrustDecisionPayload(self.test_data)
        result = client._construct_terminal_data_object()

        expected_result = {'black_box': 'testing-black-box-string', 'ip': '127.0.0.1'}
        self.assertEqual(result, expected_result)

    def test_construct_address_data_object_with_valid_required_data(self):
        client = TrustDecisionPayload(self.test_data)
        result = client._construct_address_data_object('Sumatera Utara', 'Batubara Regency')

        expected_result = {
            'country': 'ID',
            'region': 'Sumatera Utara',
            'city': 'Batubara Regency',
        }
        self.assertEqual(result, expected_result)

    def test_construct_address_data_object_with_valid_all_data(self):
        client = TrustDecisionPayload(self.test_data)
        result = client._construct_address_data_object(
            'Sumatera Utara', 'Batubara Regency', 'Tanjung Tiram', '21253'
        )

        expected_result = {
            'country': 'ID',
            'region': 'Sumatera Utara',
            'city': 'Batubara Regency',
            'district': 'Tanjung Tiram',
            'zip_code': '21253'
        }
        self.assertEqual(result, expected_result)

    def test_construct_address_data_object_with_blank_required_data(self):
        client = TrustDecisionPayload(self.test_data)
        result = client._construct_address_data_object('Sumatera Utara', None)

        self.assertEqual(result, None)

    def test_construct_phone_data_object(self):
        self.test_data.update({'phone_number': '082167912345'})
        expected_result = {'country_code': 62, 'phone_number': '082167912345'}

        client = TrustDecisionPayload(self.test_data)
        result = client._construct_phone_data_object('082167912345')

        self.assertEqual(result, expected_result)

        expected_result = {'country_code': 62, 'phone_number': '086667912345'}
        result = client._construct_phone_data_object('086667912345')

        self.assertEqual(result, expected_result)

    def test_construct_profile_data_object_with_valid_required_data(self):

        client = TrustDecisionPayload(self.test_data)
        result = client._construct_profile_data_object()

        expected_result = {
            'name': 'Edward',
            'id': {
                'id_country': 'ID',
                'id_type': 'identity_card',
                'id_number': '123123123',
            },
            'phone': {
                'country_code': 62,
                'phone_number': '62822212223'
            },
        }
        self.assertEqual(result, expected_result)

    @patch.object(TrustDecisionPayload, '_construct_address_data_object')
    def test_construct_profile_data_object_with_valid_all_data(self, mock_construct_address):
        self.test_data.update({
            'email': 'testing@gmail.com',
            'birthdate': '1997-04-13',
            'birthplace_regency': 'Kota Medan',
            'address_province': 'Sumatera Utara',
            'address_regency': 'Asahan',
            'address_subdistrict': 'Air Batu',
            'address_zip_code': '11111'
        })
        mock_construct_address.side_effect = [
            {
                'country': 'ID',
                'city': 'Kota Medan',
            },
            {
                'country': 'ID',
                'region': 'Sumatera Utara',
                'city': 'Asahan',
                'district': 'Air Batu',
                'zip_code': '11111',
            }
        ]

        client = TrustDecisionPayload(self.test_data)
        result = client._construct_profile_data_object()

        expected_result = {
            'name': 'Edward',
            'id': {
                'id_country': 'ID',
                'id_type': 'identity_card',
                'id_number': '123123123',
            },
            'phone': {
                'country_code': 62,
                'phone_number': '62822212223',
            },
            'email': 'testing@gmail.com',
            'birthdate': '1997-04-13',
            'birthplace': {
                'country': 'ID',
                'city': 'Kota Medan',
            },
            'address': {
                'country': 'ID',
                'region': 'Sumatera Utara',
                'city': 'Asahan',
                'district': 'Air Batu',
                'zip_code': '11111'
            }
        }

        self.assertEqual(result, expected_result)

    @patch.object(TrustDecisionPayload, '_construct_event_type')
    @patch.object(TrustDecisionPayload, '_construct_terminal_data_object')
    @patch.object(TrustDecisionPayload, '_construct_profile_data_object')
    def test_construct_loan_event_payload(
        self, mock_construct_profile, mock_construct_terminal, mock_construct_event_type
    ):
        mock_construct_event_type.return_value = 'login'
        mock_construct_profile.return_value = {
            'name': 'Edward',
            'id': {
                'id_country': 'ID',
                'id_type': 'identity_card',
                'id_number': '123123123',
            },
            'phone': {
                'country_code': 62,
                'phone_number': '62822212223'
            },
        }
        mock_construct_terminal.return_value = {
            'black_box': 'black-box-string-test',
            'ip': '127.0.0.1',
        }

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 1, 12, 0, 0)
        ):
            client = TrustDecisionPayload(self.test_data)
            result = client.construct_loan_event_payload()
            expected_result = {
                'event_time': '2022-05-01T12:00:00.000+07:00',
                'event_type': 'login',
                'scenario': 'default',
                'terminal': {
                    'black_box': 'black-box-string-test',
                    'ip': '127.0.0.1',
                },
                'ext': {
                    'ext_response_types': 'device_info',
                },
                'profile': {
                    'name': 'Edward',
                    'id': {
                        'id_country': 'ID',
                        'id_type': 'identity_card',
                        'id_number': '123123123',
                    },
                    'phone': {
                        'country_code': 62,
                        'phone_number': '62822212223'
                    },
                },
                'bank': {
                    'bank_branch_name': 'BCA',
                },
                'account': {
                    'account_id': '3',
                }
            }

        self.assertEqual(result, expected_result)


class TestTrustDecisionClient(TestCase):
    def setUp(self):
        self.test_data = {
            'application_id': 1,
            'fullname': 'Edward',
            'nik': '123123123',
            'event_time': '2022-05-01T12:00:00.000+07:00',
            'black_box': 'testing-black-box-string',
            'ip': '127.0.0.1',
            'phone_number': '62822212223',
            'bank_name': 'BCA',
            'address_province': None,
            'address_regency': None,
            'address_subdistrict': None,
            'address_zip_code': None,
            'event_type': 'LOGIN',
            'customer_id': 3,
            "gender": "female",
        }

    @patch('juloserver.fraud_score.clients.trust_decision.TrustDecisionPayload')
    @patch('juloserver.fraud_score.clients.trust_decision.requests')
    def test_fetch_trust_guard_loan_event(self, mock_requests, mock_trust_decision_payload):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'code': 200,
            'reasons': [
                {
                    'id': '123abc',
                    'reason': 'multi_applications_associated_with_apply_info_in_1d_loan_partner',
                }
            ],
            'result': 'accept',
            'score': 90,
            'sequence_id': '12345',
        }
        mock_response.elapsed = '00:00:00.123'
        mock_requests.post.return_value = mock_response
        mock_requests.raise_for_status.return_value = None

        mock_trust_decision_payload.construct_loan_event_payload.return_value = None

        trust_decision_client = TrustDecisionClient('partner_code', 'partner_key', 'host_url')
        result, error = trust_decision_client.fetch_trust_guard_loan_event(self.test_data, None)
        result = result.json()

        self.assertEqual(result['code'], 200)
        self.assertEqual(result['score'], 90)
        self.assertEqual(result['result'], 'accept')
        self.assertEqual(result['sequence_id'], '12345')
        self.assertFalse(error)

    @patch('juloserver.fraud_score.clients.trust_decision.requests.post',
        side_effect=requests.exceptions.RequestException())
    @patch('juloserver.fraud_score.clients.trust_decision.logger')
    def test_fetch_trust_guard_loan_event_with_request_exception(self, mock_logger, mock_post):
        trust_decision_client = TrustDecisionClient('partner_code', 'partner_key', 'host_url')
        result, error = trust_decision_client.fetch_trust_guard_loan_event(self.test_data, None)

        self.assertIsNotNone(result)
        self.assertTrue(error)

        self.assertEqual(TrustGuardApiResult.objects.count(), 0)
        self.assertEqual(TrustGuardApiRawResult.objects.count(), 0)

        mock_logger.exception.assert_called_once_with({
            'action': 'fetch_trust_guard_loan_event',
            'message': 'HTTP requests exception detected.',
            'error': mock.ANY,
            'application_id': 1,
        })

    @patch('juloserver.fraud_score.clients.trust_decision.requests.post',
        side_effect=Exception('Test error'))
    @patch('juloserver.fraud_score.clients.trust_decision.logger')
    def test_fetch_trust_guard_loan_event_with_unexpected_exception(self, mock_logger, mock_post):
        trust_decision_client = TrustDecisionClient('partner_code', 'partner_key', 'host_url')
        result, error = trust_decision_client.fetch_trust_guard_loan_event(self.test_data, None)

        self.assertEqual(result, None)
        self.assertTrue(error)

        self.assertEqual(TrustGuardApiResult.objects.count(), 0)
        self.assertEqual(TrustGuardApiRawResult.objects.count(), 0)

        mock_logger.exception.assert_called_once_with({
            'action': 'fetch_trust_guard_loan_event',
            'message': 'Unexpected error during TrustGuard score retrieval.',
            'error': mock.ANY,
            'application_id': 1,
        })
