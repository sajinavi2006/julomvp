from datetime import timedelta
from unittest import mock
import json

from django.test import TestCase, SimpleTestCase
from requests import Response
from requests.exceptions import (
    ConnectTimeout,
    ConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)
from rest_framework.exceptions import ValidationError

from juloserver.fraud_score.constants import (
    RequestErrorType,
    SeonConstant,
)
from juloserver.fraud_score.models import (
    SeonFingerprint,
    SeonFraudRawResult,
    SeonFraudRequest,
    SeonFraudResult,
)
from juloserver.fraud_score.seon_services import (
    SeonRepository,
    get_seon_repository,
    store_seon_fingerprint,
)
from juloserver.fraud_score.tests.factories import SeonFingerprintFactory
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    DeviceFactory,
)


class TestStoreSeonFingerprint(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.customer = self.application.customer

    def test_minimal_data(self):
        ret_val = store_seon_fingerprint({
            'trigger': 'custom_trigger',
            'target_type': 'application',
            'target_id': self.application.id,
            'sdk_fingerprint_hash': 'fingerprint_data'
        })

        self.assertIsInstance(ret_val, SeonFingerprint)
        self.assertEqual('custom_trigger', ret_val.trigger)
        self.assertEqual('application', ret_val.target_type)
        self.assertEqual('fingerprint_data', ret_val.sdk_fingerprint_hash)
        self.assertEqual(str(self.application.id), ret_val.target_id)

    def test_store_valid_data(self):
        ret_val = store_seon_fingerprint({
            'customer_id': self.customer.id,
            'trigger': 'application_submit',
            'ip_address': '127.0.0.1',
            'sdk_fingerprint_hash': 'seon sdk fingerprint',
            'target_type': 'application',
            'target_id': self.application.id,
        })

        self.assertIsInstance(ret_val, SeonFingerprint)
        self.assertEqual(self.customer.id, ret_val.customer_id)
        self.assertEqual('application_submit', ret_val.trigger)
        self.assertEqual('127.0.0.1', ret_val.ip_address)
        self.assertEqual('seon sdk fingerprint', ret_val.sdk_fingerprint_hash)
        self.assertEqual('application', ret_val.target_type)
        self.assertEqual(str(self.application.id), ret_val.target_id)

    def test_skip_if_no_fingerprint_data(self):
        ret_val = store_seon_fingerprint({
            'trigger': 'custom_trigger',
            'target_type': 'application',
            'target_id': self.application.id,
        })

        self.assertIsNone(ret_val)
        self.assertEqual(0, SeonFingerprint.objects.count())


    def test_store_invalid_ip_address(self):
        with self.assertRaises(ValidationError):
            store_seon_fingerprint({
                'trigger': 'custom_trigger',
                'target_type': 'application',
                'target_id': self.application.id,
                'ip_address': 'invalid ip address',
                'sdk_fingerprint_hash': 'seon sdk fingerprint',
            })


class TestSeonRepository(TestCase):
    DEFAULT_RESULT = {
        "id": "6ef6f2792e26",
        "state": "APPROVE",
        "fraud_score": 12,
        "bin_details": None,
        "version": "v2.0",
        "applied_rules": None,
        "device_details": None,
        "calculation_time": 26,
        "seon_id": 2,
        "ip_details": None,
        "email_details": None,
        "phone_details": None
    }

    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.mock_seon_client = mock.MagicMock()

        # mock the uuid4 function to return a predictable value
        self.mock_uuid4_obj = mock.MagicMock()
        self.mock_uuid4_obj.hex = 'generated_uuid'

    def _construct_seon_response(self, result, status_code=200, errors=None):
        response = Response()
        response.status_code = status_code
        response._content = json.dumps({
            'success': True if status_code != 200 else False,
            'error': errors if errors else {},
            'data': result,
        }).encode('utf-8')
        response.encoding = 'UTF-8'
        response.elapsed = timedelta(seconds=1)
        return response

    def test_fetch_api_result_minimal_data(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        seon_result = self.DEFAULT_RESULT
        seon_response = self._construct_seon_response(seon_result)
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        ret_val = seon_repository.fetch_fraud_api_result(seon_fingerprint)

        self.assertIsInstance(ret_val, SeonFraudResult)
        self.assertEqual(2, ret_val.seon_id)
        self.assertEqual('APPROVE', ret_val.state)
        self.assertEqual(12, ret_val.fraud_score)
        self.assertEqual(26, ret_val.calculation_time)
        self.assertEqual('v2.0', ret_val.version)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertEqual(200, seon_request.response_code)
        self.assertEqual(1000, seon_request.response_time)
        self.assertIsNone(seon_request.error_type)
        self.assertEqual(seon_request.id, ret_val.seon_fraud_request_id)

        seon_raw_result = ret_val.raw_result
        self.assertIsInstance(seon_raw_result, SeonFraudRawResult)
        self.assertIsNotNone(seon_raw_result.raw)

    def test_http_error_4xx(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        seon_response = self._construct_seon_response({}, status_code=401, errors={
            "code": "2002",
            "message": "invalid license key"
        })
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        with self.assertRaises(HTTPError):
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertEqual(401, seon_request.response_code)
        self.assertEqual(1000, seon_request.response_time)
        self.assertEquals(RequestErrorType.HTTP_ERROR, seon_request.error_type)
        self.assertEqual('2002', seon_request.seon_error_code)

    def test_connect_timeout(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        self.mock_seon_client.fetch_fraud_api.side_effect = ConnectTimeout()

        seon_repository = SeonRepository(self.mock_seon_client)
        with self.assertRaises(ConnectTimeout):
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertIsNone(seon_request.response_code)
        self.assertIsNone(seon_request.response_time)
        self.assertEquals(
            RequestErrorType.CONNECT_TIMEOUT_ERROR,
            seon_request.error_type,
        )

    def test_read_timeout(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        self.mock_seon_client.fetch_fraud_api.side_effect = ReadTimeout()

        seon_repository = SeonRepository(self.mock_seon_client)
        with self.assertRaises(ReadTimeout):
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertIsNone(seon_request.response_code)
        self.assertIsNone(seon_request.response_time)
        self.assertEquals(
            RequestErrorType.READ_TIMEOUT_ERROR,
            seon_request.error_type,
        )

    def test_request_exception(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        self.mock_seon_client.fetch_fraud_api.side_effect = RequestException()

        seon_repository = SeonRepository(self.mock_seon_client)
        with self.assertRaises(RequestException):
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertIsNone(seon_request.response_code)
        self.assertIsNone(seon_request.response_time)
        self.assertEquals(
            RequestErrorType.OTHER_ERROR,
            seon_request.error_type,
        )

    def test_connection_error(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        self.mock_seon_client.fetch_fraud_api.side_effect = ConnectionError()

        seon_repository = SeonRepository(self.mock_seon_client)
        with self.assertRaises(ConnectionError):
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertIsNone(seon_request.response_code)
        self.assertIsNone(seon_request.response_time)
        self.assertEquals(
            RequestErrorType.CONNECTION_ERROR,
            seon_request.error_type,
        )

    def test_other_exception(self):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        self.mock_seon_client.fetch_fraud_api.side_effect = Exception()

        seon_repository = SeonRepository(self.mock_seon_client)
        with self.assertRaises(Exception):
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

        seon_request = SeonFraudRequest.objects.get(seon_fingerprint=seon_fingerprint)
        self.assertIsNone(seon_request.response_code)
        self.assertIsNone(seon_request.response_time)
        self.assertEquals(
            RequestErrorType.UNKNOWN_ERROR,
            seon_request.error_type,
        )

    @mock.patch('juloserver.fraud_score.seon_services.uuid')
    def test_request_config_data(self, mock_uuid):
        mock_uuid.uuid4.return_value = self.mock_uuid4_obj

        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        seon_result = self.DEFAULT_RESULT
        seon_response = self._construct_seon_response(seon_result)
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        seon_repository.fetch_fraud_api_result(seon_fingerprint)

        self.mock_seon_client.fetch_fraud_api.assert_called_once_with({
            'config': {
                "ip": {
                    "include": "flags,history,id",
                    "version": "v1.1",
                },
                "email": {
                    "include": "flags,history,id",
                    "version": "v2.2",
                    "timeout": 3000,
                },
                "phone": {
                    "include": "flags,history,id",
                    "version": "v1.4",
                    "timeout": 3000,
                },
                "ip_api": True,
                "email_api": True,
                "phone_api": True,
                "device_fingerprinting": True
            },
            'action_type': None,
            'transaction_id': 'generated_uuid',
            'ip': None,
            'session': None,
        })

    @mock.patch('juloserver.fraud_score.seon_services.uuid')
    def test_construct_fingerprint_data(self, mock_uuid):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            ip_address='127.0.0.1',
            sdk_fingerprint_hash='test_sdk_fingerprint_hash',
            target_type='custom_type',
            target_id='123',
        )
        mock_uuid.uuid4.return_value = self.mock_uuid4_obj

        seon_result = self.DEFAULT_RESULT
        seon_response = self._construct_seon_response(seon_result)
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        seon_repository.seon_config = {}
        seon_repository.fetch_fraud_api_result(seon_fingerprint)

        self.mock_seon_client.fetch_fraud_api.assert_called_once_with({
            'config': {},
            'action_type': None,
            'transaction_id': 'generated_uuid',
            'ip': '127.0.0.1',
            'session': 'test_sdk_fingerprint_hash',
        })

    @mock.patch('juloserver.fraud_score.seon_services.uuid')
    def test_construct_action_types(self, mock_uuid):
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )
        mock_uuid.uuid4.return_value = self.mock_uuid4_obj

        seon_result = self.DEFAULT_RESULT
        seon_response = self._construct_seon_response(seon_result)
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        seon_repository.seon_config = {}

        expected_action_map = {
            SeonConstant.Trigger.APPLICATION_SUBMIT: 'account_register'
        }
        for trigger, expected_action_type in expected_action_map.items():
            self.mock_seon_client.fetch_fraud_api.reset_mock()
            seon_fingerprint.trigger = trigger
            seon_repository.fetch_fraud_api_result(seon_fingerprint)

            self.mock_seon_client.fetch_fraud_api.assert_called_with({
                'config': {},
                'action_type': expected_action_type,
                'transaction_id': 'generated_uuid',
                'ip': None,
                'session': None,
            })

    @mock.patch('juloserver.fraud_score.seon_services.uuid')
    @mock.patch('juloserver.fraud_score.seon_services.sha1')
    def test_construct_customer_data(self, mock_sha1, mock_uuid):
        customer = CustomerFactory(customer_xid=1234567890)
        seon_fingerprint = SeonFingerprintFactory(
            customer=customer,
            trigger='custom_trigger',
            target_type='custom_type',
            target_id='123',
        )

        mock_sha1.return_value.hexdigest.return_value = 'hashed_password'
        mock_uuid.uuid4.return_value = self.mock_uuid4_obj

        seon_result = self.DEFAULT_RESULT
        seon_response = self._construct_seon_response(seon_result)
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        seon_repository.seon_config = {}
        seon_repository.fetch_fraud_api_result(seon_fingerprint)

        self.mock_seon_client.fetch_fraud_api.assert_called_once_with({
            'config': {},
            'action_type': None,
            'transaction_id': 'generated_uuid',
            'ip': None,
            'session': None,
            'user_id': 1234567890,
            'user_created': int(customer.cdate.timestamp()),
            'password_hash': 'hashed_password',
        })

    @mock.patch('juloserver.fraud_score.seon_services.uuid')
    def test_construct_application_data(self, mock_uuid):
        application = ApplicationJ1Factory(
            fullname='John Doe',
            email='test.email@example.com',
            mobile_phone_1='081234567890',
            dob='1990-01-01',
            birth_place='birthplace',
            address_provinsi='address-provinsi',
            address_kabupaten='address-kabupaten',
            address_kodepos='12345',
            address_street_num='address-street-num',
            name_in_bank='name-in-bank',
            device=DeviceFactory(android_id='test-android-id'),
            loan_purpose='loan-purpose',
            referral_code='referral-code',
        )
        seon_fingerprint = SeonFingerprintFactory(
            trigger='custom_trigger',
            target_type='application',
            target_id=application.id,
        )

        mock_uuid.uuid4.return_value = self.mock_uuid4_obj

        seon_result = self.DEFAULT_RESULT
        seon_response = self._construct_seon_response(seon_result)
        self.mock_seon_client.fetch_fraud_api.return_value = seon_response

        seon_repository = SeonRepository(self.mock_seon_client)
        seon_repository.seon_config = {}
        seon_repository.fetch_fraud_api_result(seon_fingerprint)

        self.mock_seon_client.fetch_fraud_api.assert_called_once_with({
            'config': {},
            'action_type': None,
            'transaction_id': 'generated_uuid',
            'ip': None,
            'session': None,
            'user_fullname': 'John Doe',
            'email': 'test.email@example.com',
            'phone_number': '+6281234567890',
            'user_dob': '1990-01-01',
            'user_pob': 'birthplace',
            'user_region': 'address-provinsi',
            'user_city': 'address-kabupaten',
            'user_zip': '12345',
            'user_street': 'address-street-num',
            'user_bank_name': 'name-in-bank',
            'device_id': 'test-android-id',
            'order_memo': 'loan-purpose',
            'affiliate_id': 'referral-code',
        })


class TestGetSeonRepository(SimpleTestCase):
    def test_get_seon_repository(self):
        seon_repository = get_seon_repository()
        self.assertIsInstance(seon_repository, SeonRepository)
