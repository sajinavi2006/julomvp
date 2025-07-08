import requests
from django.test.testcases import TestCase
from mock.mock import (
    Mock,
    patch,
)

from juloserver.fraud_score.models import (
    FinscoreApiRawResult,
    FinscoreApiRequest,
    FinscoreApiResult,
    TrustGuardApiRawResult,
    TrustGuardApiRequest,
    TrustGuardApiResult,
)
from juloserver.fraud_score.trust_decision_tasks import (
    execute_finscore_result,
    execute_trust_guard_for_loan_event,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    DeviceFactory,
)
from unittest import mock


class TestExecuteTrustGuardForLoanEvent(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.device = DeviceFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            device=self.device,
            fullname='Edward',
            ktp='123123123',
            mobile_phone_1='62822212223',
            email=None,
            dob=None,
            birth_place=None,
            address_provinsi=None,
            address_kabupaten=None,
            address_kecamatan=None,
            address_kodepos=None
        )
        self.feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.TRUST_GUARD_SCORING,
            parameters={'trust_guard': True, 'finscore': False},
            is_active=True,
        )

    @patch('juloserver.fraud_score.trust_decision_tasks.is_eligible_for_trust_decision')
    @patch('juloserver.fraud_score.trust_decision_tasks.get_trust_decision_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_trust_decision_payload')
    @patch('juloserver.fraud_score.trust_decision_tasks.execute_finscore_result.delay')
    def test_success(
        self,
        mock_execute_finscore,
        mock_parse_data,
        mock_trust_decision_client,
        mock_is_eligible_for_trust_decision,
    ):
        mock_is_eligible_for_trust_decision.return_value = True
        mock_parse_data.return_value = None
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'code': 200,
            'device_info': {
                'device_id': 'test-device-id',
            },
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
        mock_trust_decision_client.return_value.fetch_trust_guard_loan_event.return_value = \
            [mock_response, False]

        result, error, error_message = execute_trust_guard_for_loan_event(
            self.application.id, 'testing-black-box-string', 'LOGIN')

        self.assertEqual(error, False)
        self.assertEqual(error_message, None)

        trust_api_request = TrustGuardApiRequest.objects.last()
        self.assertEqual(trust_api_request.application.id, self.application.id)
        self.assertEqual(trust_api_request.black_box, 'testing-black-box-string')

        trust_api_result = TrustGuardApiResult.objects.last()
        self.assertEqual(trust_api_result.code, 200)
        self.assertEqual(trust_api_result.score, 90)
        self.assertEqual(trust_api_result.result, 'accept')
        self.assertEqual(trust_api_result.sequence_id, '12345')

        trust_api_raw_result = TrustGuardApiRawResult.objects.last()
        self.assertEqual(trust_api_raw_result.http_code, 200)
        self.assertEqual(trust_api_raw_result.response_json, result)

        mock_execute_finscore.assert_called_once_with(
            self.application.id, 'LOGIN', 'test-device-id'
        )

    @patch('juloserver.fraud_score.trust_decision_tasks.is_eligible_for_trust_decision')
    @patch('juloserver.fraud_score.trust_decision_tasks.get_trust_decision_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_trust_decision_payload')
    @patch('juloserver.fraud_score.trust_decision_tasks.execute_finscore_result.delay')
    def test_error_process(
        self,
        mock_execute_finscore,
        mock_parse_data,
        mock_trust_decision_client,
        mock_is_eligible_for_trust_decision,
    ):
        mock_is_eligible_for_trust_decision.return_value = True
        mock_parse_data.return_value = None
        mock_response = Mock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.headers = {"Content-Type": "text/plain"}
        mock_response.text = "Internal server error"
        mock_response.json.side_effect = ValueError("no JSON")
        mock_trust_decision_client.return_value.fetch_trust_guard_loan_event.return_value = \
            [mock_response, True]

        execute_trust_guard_for_loan_event(self.application.id, 'testing-black-box-string', 'LOGIN')

        trust_api_raw_result = TrustGuardApiRawResult.objects.last()
        self.assertEqual(trust_api_raw_result.http_code, 500)
        self.assertIsNotNone(trust_api_raw_result.response_json)

        mock_execute_finscore.assert_called_once_with(self.application.id, 'LOGIN')

    @patch('juloserver.fraud_score.trust_decision_tasks.is_eligible_for_trust_decision')
    @patch('juloserver.fraud_score.trust_decision_tasks.execute_finscore_result.delay')
    @patch('juloserver.fraud_score.trust_decision_tasks.get_trust_decision_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_trust_decision_payload')
    def test_fail_response(
        self,
        mock_parse_data,
        mock_trust_decision_client,
        mock_execute_finscore,
        mock_is_eligible_for_trust_decision,
    ):
        mock_is_eligible_for_trust_decision.return_value = True
        self.feature_setting.update_safely(parameters={'trust_guard': True, 'finscore': True})

        mock_parse_data.return_value = None
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'code': 10001,
            'message': 'phone.phone_number format error',
            'success': False
        }
        mock_trust_decision_client.return_value.fetch_trust_guard_loan_event.return_value = \
            [mock_response, False]

        result, error, error_message = execute_trust_guard_for_loan_event(
            self.application.id, 'testing-black-box-string', 'LOGIN')

        trust_api_request = TrustGuardApiRequest.objects.last()
        self.assertEqual(trust_api_request.application.id, self.application.id)
        self.assertEqual(trust_api_request.black_box, 'testing-black-box-string')

        trust_raw_api_result = TrustGuardApiRawResult.objects.last()
        self.assertEqual(trust_raw_api_result.response_json, mock_response.json.return_value)

        self.assertEqual(error, True)
        self.assertEqual(error_message, 'Trust Guard Non-200 API Status Code Received')
        mock_execute_finscore.assert_called_once_with(
            self.application.id, 'LOGIN'
        )

    @patch('juloserver.fraud_score.trust_decision_tasks.is_eligible_for_trust_decision')
    @patch('juloserver.fraud_score.trust_decision_tasks.logger')
    def test_application_not_eligible(self, mock_logger, mock_is_eligible_for_trust_decision):
        mock_is_eligible_for_trust_decision.return_value = False

        result, error, error_message = execute_trust_guard_for_loan_event(
            self.application.id, 'black-box-string-test', 'LOGIN'
        )

        self.assertEqual(result, {})
        self.assertEqual(error, True)
        self.assertEqual(error_message, "Application is not eligible for trust decision")
        mock_logger.info.assert_has_calls([
            mock.call({
                'function': 'TrustGuardScoreView execute_trust_guard_for_loan_event',
                'application_id': self.application.id,
                'black_box': 'black-box-string-test',
                'device_type': 'android',
            }),
            mock.call({
                'action': 'execute_trust_guard_for_loan_event',
                'message': 'Application is not eligible for trust decision.',
                'application_id': self.application.id,
            }),
        ])

    @patch('juloserver.fraud_score.trust_decision_tasks.is_eligible_for_trust_decision')
    def test_success_store_blackbox(self, mock_is_eligible_for_trust_decision):
        mock_is_eligible_for_trust_decision.return_value = True

        execute_trust_guard_for_loan_event(self.application.id, 'testing-black-box-string', 'LOGIN')

        trust_api_request = TrustGuardApiRequest.objects.last()
        self.assertEqual(trust_api_request.application.id, self.application.id)
        self.assertEqual(trust_api_request.black_box, 'testing-black-box-string')

        self.feature_setting.update_safely(parameters={'trust_guard': False, 'finscore': False})
        self.feature_setting2 = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.ABC_TRUST_GUARD,
            is_active=True,
        )

        execute_trust_guard_for_loan_event(
            self.application.id, 'testing-black-box-string2', 'LOGIN'
        )

        trust_api_request = TrustGuardApiRequest.objects.last()
        self.assertEqual(trust_api_request.application.id, self.application.id)
        self.assertEqual(trust_api_request.black_box, 'testing-black-box-string2')

        self.feature_setting2.update_safely(is_active=False)
        execute_trust_guard_for_loan_event(
            self.application.id, 'testing-black-box-string3', 'LOGIN'
        )

        trust_api_request = TrustGuardApiRequest.objects.last()
        self.assertEqual(trust_api_request.application.id, self.application.id)
        self.assertEqual(trust_api_request.black_box, 'testing-black-box-string2')


class TestExecuteFinscoreResult(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            fullname='Edward',
            ktp='123123123',
            mobile_phone_1='62822212223',
        )
        self.feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.TRUST_GUARD_SCORING,
            parameters={'trust_guard': False, 'finscore': True}
        )
        self.event_type = 'APPLICATION'

    @patch('juloserver.fraud_score.trust_decision_tasks.get_finscore_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_finscore_payload')
    def test_success(self, mock_parse_data, mock_finscore_client):
        mock_parse_data.return_value = None
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
        mock_finscore_client.return_value.fetch_finscore_result.return_value = \
            [mock_response, False]

        execute_finscore_result(self.application.id, self.event_type, 'any-device-id')

        finscore_api_request = FinscoreApiRequest.objects.last()
        self.assertEqual(finscore_api_request.application.id, self.application.id)
        self.assertEqual(finscore_api_request.device_id, 'any-device-id')

        finscore_api_result = FinscoreApiResult.objects.last()
        self.assertEqual(finscore_api_result.code, 0)
        self.assertEqual(finscore_api_result.reason_code, 200)
        self.assertEqual(finscore_api_result.value, 821.0)

        finscore_api_raw_result = FinscoreApiRawResult.objects.last()
        self.assertEqual(finscore_api_raw_result.http_code, 200)

    @patch('juloserver.fraud_score.trust_decision_tasks.get_finscore_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_finscore_payload')
    def test_fail_response(self, mock_parse_data, mock_finscore_client):
        mock_parse_data.return_value = None
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'code': 10001,
            'message': 'phone.phone_number format error',
            'success': False
        }
        mock_finscore_client.return_value.fetch_finscore_result.return_value = \
            [mock_response, False]

        execute_finscore_result(self.application.id, self.event_type, 'any-device-id')

        finscore_api_request = FinscoreApiRequest.objects.last()
        self.assertEqual(finscore_api_request.application.id, self.application.id)
        self.assertEqual(finscore_api_request.device_id, 'any-device-id')

        finscore_api_raw_result = FinscoreApiRawResult.objects.last()
        self.assertEqual(finscore_api_raw_result.response_json, mock_response.json.return_value)

        self.assertEqual(FinscoreApiResult.objects.count(), 0)

    @patch('juloserver.fraud_score.trust_decision_tasks.get_finscore_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_finscore_payload')
    @patch('juloserver.fraud_score.trust_decision_tasks.logger')
    def test_error_process(self, mock_logger, mock_parse_data, mock_finscore_client):
        mock_parse_data.return_value = {
            'application_id': self.application.id,
        }
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.headers = {
            'content_type': 'application/json'
        }
        mock_response.json.return_value = {
            'code': 10001,
            'message': 'phone.phone_number format error',
            'success': False
        }
        mock_finscore_client.return_value.fetch_finscore_result.return_value = \
            [mock_response, True]

        execute_finscore_result(self.application.id, self.event_type, 'any-device-id')

        finscore_api_request = FinscoreApiRequest.objects.last()
        self.assertEqual(finscore_api_request.application.id, self.application.id)
        self.assertEqual(finscore_api_request.device_id, 'any-device-id')

        finscore_api_raw_result = FinscoreApiRawResult.objects.last()
        self.assertEqual(finscore_api_raw_result.response_json, mock_response.json.return_value)

        self.assertEqual(FinscoreApiResult.objects.count(), 0)

        mock_logger.info.assert_called_once_with({
            'action': 'execute_finscore_result',
            'message': 'Unexpected error detected.',
            'application_id': self.application.id,
            'trust_guard_api_raw_result': finscore_api_raw_result.id,
            'response': mock_response.json.return_value,
        })

    @patch('juloserver.fraud_score.trust_decision_tasks.get_finscore_client')
    @patch('juloserver.fraud_score.trust_decision_tasks.parse_data_for_finscore_payload')
    @patch('juloserver.fraud_score.trust_decision_tasks.logger')
    def test_result_code_not_0(self, mock_logger, mock_parse_data, mock_finscore_client):
        mock_parse_data.return_value = {'application_id': self.application.id}
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'code': 210,
            'data': None,
            'message': 'Required fields are missing or incorrect.',
            'success': False
        }
        mock_response.elapsed = '00:00:00.123'
        mock_finscore_client.return_value.fetch_finscore_result.return_value = \
            [mock_response, False]

        execute_finscore_result(self.application.id, self.event_type, 'any-device-id')

        finscore_api_request = FinscoreApiRequest.objects.last()
        self.assertEqual(finscore_api_request.application.id, self.application.id)
        self.assertEqual(finscore_api_request.device_id, 'any-device-id')

        finscore_api_raw_result = FinscoreApiRawResult.objects.last()
        self.assertEqual(finscore_api_raw_result.http_code, 200)

        self.assertEqual(FinscoreApiResult.objects.count(), 0)

        mock_logger.info.assert_called_once_with({
            'action': 'execute_finscore_result',
            'message': 'Non 0 API status code received.',
            'application_id': self.application.id,
            'trust_guard_api_raw_result': finscore_api_raw_result.id,
        })

    @patch('juloserver.fraud_score.trust_decision_tasks.logger')
    def test_with_event_type_not_application(self, mock_logger):
        execute_finscore_result(self.application.id, 'LOGIN', 'any-device-id')

        mock_logger.info.assert_called_once_with({
            'action': 'execute_finscore_result',
            'message': 'Event type is not APPLICATION.',
            'application_id': self.application.id,
        })

    @patch('juloserver.fraud_score.trust_decision_tasks.logger')
    def test_with_inactive_feature_setting(self, mock_logger):
        self.feature_setting.update_safely(parameters={'trust_guard': False, 'finscore': False})

        execute_finscore_result(self.application.id, self.event_type, 'any-device-id')

        mock_logger.info.assert_called_once_with({
            'action': 'execute_finscore_result',
            'message': 'Feature setting is turned off.',
            'application_id': self.application.id,
        })
