import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from requests import (
    HTTPError,
    Response,
)

from juloserver.fraud_score.clients.monnai_client import (
    MonnaiClient,
)
from juloserver.fraud_score.constants import MonnaiConstants
from juloserver.fraud_score.exceptions import IncompleteRequestData
from juloserver.fraud_score.monnai_services import (
    MonnaiRepository,
    get_monnai_repository,
)
from juloserver.fraud_score.tests.factories import (
    TelcoLocationResultFactory,
    MaidResultFactory,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    DeviceIpHistoryFactory,
    AddressGeolocationFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
)


class TestGetMonnaiRepository(TestCase):
    @mock.patch('juloserver.fraud_score.monnai_services.get_redis_client')
    def test_get_monnai_repository(self, mock_redis_client):
        monnai_repo = get_monnai_repository()

        self.assertIsInstance(monnai_repo, MonnaiRepository)
        self.assertIsInstance(monnai_repo.monnai_client, MonnaiClient)
        mock_redis_client.assert_called_once()


class TestMonnaiRepository(TestCase):
    def setUp(self):
        self.mock_monnai_client = mock.MagicMock()
        self.mock_redis_client = mock.MagicMock()
        self.monnai_repository = MonnaiRepository(
            monnai_client=self.mock_monnai_client,
            redis_client=self.mock_redis_client,
        )

    @mock.patch('juloserver.fraud_score.monnai_services.get_application_submission_ip_history')
    def test_construct_application_submission_data(
        self,
        mock_get_application_submission_ip_history,
    ):
        application = ApplicationJ1Factory(
            mobile_phone_1='0812345678',
            email='test.email@test.com',
            customer=CustomerFactory(advertising_id='advertising-id'),
        )
        device_ip_history = DeviceIpHistoryFactory(
            customer=application.customer,
            ip_address='192.168.0.1',
        )
        mock_get_application_submission_ip_history.return_value = device_ip_history
        ret_val = self.monnai_repository._construct_application_submission_data(application)

        expected_result = {
            'phoneNumber': '+62812345678',
            'phoneDefaultCountryCode': 'ID',
            'email': 'test.email@test.com',
            'ipAddress': '192.168.0.1',
            'deviceIds': ['advertising-id'],
            'countryCode': 'ID',
        }
        self.assertEqual(expected_result, ret_val)
        mock_get_application_submission_ip_history.assert_called_once_with(application)

    @mock.patch('juloserver.fraud_score.monnai_services.get_application_submission_ip_history')
    def test_construct_application_submission_data_invalid_phone(
        self,
        mock_get_application_submission_ip_history,
    ):
        application = ApplicationJ1Factory(
            mobile_phone_1='08123',
            email='test.email@test.com',
            customer=CustomerFactory(advertising_id='advertising-id'),
        )
        device_ip_history = DeviceIpHistoryFactory(
            customer=application.customer,
            ip_address='192.168.0.1',
        )
        mock_get_application_submission_ip_history.return_value = device_ip_history

        with self.assertRaises(IncompleteRequestData) as context:
            self.monnai_repository._construct_application_submission_data(application)

        expected_result = {
            'phoneNumber': None,
            'phoneDefaultCountryCode': 'ID',
            'email': 'test.email@test.com',
            'ipAddress': '192.168.0.1',
            'deviceIds': ['advertising-id'],
            'countryCode': 'ID',
        }
        self.assertEqual(expected_result, context.exception.request_data)

    @mock.patch('juloserver.fraud_score.monnai_services.get_application_submission_ip_history')
    def test_construct_application_submission_data_no_ip(
        self,
        mock_get_application_submission_ip_history,
    ):
        application = ApplicationJ1Factory(
            mobile_phone_1='0812345678',
            email='test.email@test.com',
            customer=CustomerFactory(advertising_id='advertising-id'),
        )
        mock_get_application_submission_ip_history.return_value = None

        with self.assertRaises(IncompleteRequestData) as context:
            self.monnai_repository._construct_application_submission_data(application)

        expected_result = {
            'phoneNumber': '+62812345678',
            'phoneDefaultCountryCode': 'ID',
            'email': 'test.email@test.com',
            'ipAddress': None,
            'deviceIds': ['advertising-id'],
            'countryCode': 'ID',
        }
        self.assertEqual(expected_result, context.exception.request_data)

    @mock.patch('juloserver.fraud_score.monnai_services.get_application_submission_ip_history')
    def test_construct_application_submission_data_no_advertising_id(
        self,
        mock_get_application_submission_ip_history,
    ):
        application = ApplicationJ1Factory(
            mobile_phone_1='0812345678',
            email='test.email@test.com',
            customer=CustomerFactory(advertising_id=''),
        )
        mock_get_application_submission_ip_history.return_value = None

        with self.assertRaises(IncompleteRequestData) as context:
            self.monnai_repository._construct_application_submission_data(application)

        expected_result = {
            'phoneNumber': '+62812345678',
            'phoneDefaultCountryCode': 'ID',
            'email': 'test.email@test.com',
            'ipAddress': None,
            'deviceIds': [],
            'countryCode': 'ID',
        }
        self.assertEqual(expected_result, context.exception.request_data)

    def test_authenticate_no_cache(self):
        self.mock_redis_client.get.return_value = None
        self.mock_monnai_client.fetch_access_token.return_value = ('access_token', 120)

        ret_val = self.monnai_repository.authenticate()

        expected_key = 'fraud_score::monnai::access_token::289ec216ac23720564c0c142c4566378'
        self.assertEqual('access_token', ret_val)
        self.mock_redis_client.get.assert_called_once_with(expected_key)
        self.mock_redis_client.set.assert_called_once_with(
            expected_key,
            'access_token',
            timedelta(seconds=90)
        )

        expected_scopes = [
            'insights/phone_basic',
            'insights/phone_social',
            'insights/email_basic',
            'insights/email_social',
            'insights/ip_basic',
            'insights/identity_enrichment',
            'insights/identity_correlation',
            'insights/device_details',
            'insights/address_verification'
        ]
        self.mock_monnai_client.fetch_access_token.assert_called_once_with(
            scopes=expected_scopes,
        )

    def test_authenticate_with_cache(self):
        self.mock_redis_client.get.return_value = 'access_token_cache'

        ret_val = self.monnai_repository.authenticate()

        expected_key = 'fraud_score::monnai::access_token::289ec216ac23720564c0c142c4566378'
        self.assertEqual('access_token_cache', ret_val)
        self.mock_redis_client.get.assert_called_once_with(expected_key)
        self.mock_monnai_client.fetch_access_token.assert_not_called()


class TestMonnaiRepositoryValidateRequestData(TestCase):
    def setUp(self):
        self.mock_monnai_client = mock.MagicMock()
        self.mock_redis_client = mock.MagicMock()

        self.mock_redis_client.get.return_value = 'access_token'

        self.monnai_repository = MonnaiRepository(self.mock_monnai_client, self.mock_redis_client)

    def test_no_validation_failure(self):
        try:
            test_payload = {
                'eventType': 'ACCOUNT_CREATION',
                'packages': ['SOME_PACKAGE'],
                'phoneNumber': '082134567890'
            }
            self.monnai_repository._validate_request_data(test_payload)
        except Exception as e:
            self.fail('test_no_validation_failure raised unexpected Exception: {}'.format(str(e)))

    def test_validation_failure(self):
        # Test empty list
        test_payload = {
            'eventType': 'ACCOUNT_CREATION',
            'packages': [],
            'phoneNumber': '082134567890'
        }

        with self.assertRaises(IncompleteRequestData):
            self.monnai_repository._validate_request_data(test_payload)

        # Test None value
        test_payload = {
            'eventType': 'ACCOUNT_CREATION',
            'packages': ['SOME_PACKAGE'],
            'phoneNumber': None
        }
        with self.assertRaises(IncompleteRequestData):
            self.monnai_repository._validate_request_data(test_payload)

        # Test empty string
        test_payload = {
            'eventType': 'ACCOUNT_CREATION',
            'packages': ['SOME_PACKAGE'],
            'phoneNumber': ''
        }
        with self.assertRaises(IncompleteRequestData):
            self.monnai_repository._validate_request_data(test_payload)


class TestMonnaiRepositoryConstructPayloadForAddressVerificationAndDeviceDetail(TestCase):
    def setUp(self):
        self.mock_monnai_client = mock.MagicMock()
        self.mock_redis_client = mock.MagicMock()
        self.mock_redis_client.get.return_value = 'access_token'
        self.monnai_repository = MonnaiRepository(self.mock_monnai_client, self.mock_redis_client)

        self.customer_with_advertising_id = CustomerFactory(advertising_id='advertising-id')
        self.application = ApplicationJ1Factory(customer=self.customer_with_advertising_id)
        self.address_geolocation = AddressGeolocationFactory(
            application=self.application, latitude=-1.23, longitude=123.456
        )

    @mock.patch('juloserver.fraud_score.monnai_services.logger')
    def test_construct_with_invalid_phone_number_cause_warning_logger(self, mock_logger):
        self.application.update_safely(mobile_phone_1='22')
        expected_payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': ['DEVICE_DETAILS'],
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': None,
            'locationCoordinates': {
                'latitude': self.address_geolocation.latitude,
                'longitude': self.address_geolocation.longitude,
            },
            'deviceIds': ['advertising-id'],
            'cleansingFlag': True,
        }

        result = (
            self.monnai_repository._construct_payload_for_address_verification_and_device_detail(
                self.application, '22', ['DEVICE_DETAILS']
            )
        )

        mock_logger.warning.assert_called_once_with({
            'message': 'Invalid phone number error',
            'exception': 'Invalid phone number [22]',
            'mobile_phone_1': self.application.mobile_phone_1,
            'action': 'MonnaiRepository::_construct_payload_for_address_verification_and_device_detail',
            'application_id': self.application.id,
        }, exc_info=True)
        self.assertEqual(result, expected_payload)

    @mock.patch('juloserver.fraud_score.monnai_services.logger')
    def test_construct_with_valid_phone_number_not_trigger_warning_logger(self, mock_logger):
        self.application_history = ApplicationHistoryFactory(
            status_old=ApplicationStatusCodes.FORM_CREATED,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
            application_id=self.application.id,
        )
        self.application.update_safely(mobile_phone_1='082167912345')
        expected_payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': ['ADDRESS_VERIFICATION', 'DEVICE_DETAILS'],
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': '+6282167912345',
            'locationCoordinates': {
                'latitude': self.address_geolocation.latitude,
                'longitude': self.address_geolocation.longitude,
            },
            'deviceIds': ['advertising-id'],
            'cleansingFlag': True,
            'consentDetails': {
                'consentId': str(self.application.customer.id),
                'consentTimestamp': str(
                    self.application_history.cdate.strftime(MonnaiConstants.TIMESTAMPFORMAT)
                ),
                'consentType': MonnaiConstants.APP,
            },
        }

        result = (
            self.monnai_repository._construct_payload_for_address_verification_and_device_detail(
                self.application, '082167912345', ['ADDRESS_VERIFICATION', 'DEVICE_DETAILS']
            )
        )
        mock_logger.warning.assert_not_called()
        self.assertEqual(result, expected_payload)


class TestMonnaiRepositoryAdditionalPayloadForAddressVerification(TestCase):
    def setUp(self):
        self.mock_monnai_client = mock.MagicMock()
        self.mock_redis_client = mock.MagicMock()
        self.mock_redis_client.get.return_value = 'access_token'
        self.monnai_repository = MonnaiRepository(self.mock_monnai_client, self.mock_redis_client)

        self.customer_with_advertising_id = CustomerFactory(advertising_id='advertising-id')
        self.application = ApplicationJ1Factory(
            customer=self.customer_with_advertising_id,
            mobile_phone_1='08123456789',
            address_street_num='JL. Selat Karimata 11',
            address_kelurahan='Duren Sawit',
            address_kecamatan='Duren Sawit',
            address_kabupaten='Kota Jakarta Timur',
            address_provinsi='DKI Jakarta',
            address_kodepos='13440'
        )
        self.address_geolocation = AddressGeolocationFactory(
            application=self.application, latitude=-1.23, longitude=123.456
        )

    def test_success_add_additional_payload(self):
        expected_payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': ['ADDRESS_VERIFICATION'],
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': None,
            'locationCoordinates': {
                'latitude': self.address_geolocation.latitude,
                'longitude': self.address_geolocation.longitude,
            },
            'deviceIds': ['advertising-id'],
            "address": {
                "addressLine1": "JL. Selat Karimata 11",
                "addressLine2": None,
                "addressLine3": "Duren Sawit, Kecamatan Duren Sawit",
                "addressLine4": "Kota Jakarta Timur, DKI Jakarta",
                "city": "Kota Jakarta Timur",
                "state": None,
                "postalCode": "13440",
                "country": "Indonesia"
            },
        }

        previous_payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': ['ADDRESS_VERIFICATION'],
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': None,
            'locationCoordinates': {
                'latitude': self.address_geolocation.latitude,
                'longitude': self.address_geolocation.longitude,
            },
            'deviceIds': ['advertising-id']
        } 
        result = (
            self.monnai_repository._additional_payload_for_address_verification(
                previous_payload, self.application
            )
        )
        self.assertEqual(result, expected_payload)

    def test_skip_add_additional_payload(self):
        self.application.update_safely(address_street_num=None)
        expected_payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': ['ADDRESS_VERIFICATION'],
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': None,
            'locationCoordinates': {
                'latitude': self.address_geolocation.latitude,
                'longitude': self.address_geolocation.longitude,
            },
            'deviceIds': ['advertising-id']
        }

        previous_payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': ['ADDRESS_VERIFICATION'],
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': None,
            'locationCoordinates': {
                'latitude': self.address_geolocation.latitude,
                'longitude': self.address_geolocation.longitude,
            },
            'deviceIds': ['advertising-id']
        } 
        result = (
            self.monnai_repository._additional_payload_for_address_verification(
                previous_payload, self.application
            )
        )
        self.assertEqual(result, expected_payload)


class TestMonnaiRepositoryFetchInsightApplicationForAddressVerificationAndDeviceDetailResult(TestCase):
    def setUp(self):
        super().setUp()
        self.patch_construct_payload_for_address_verification_and_device_detail = mock.patch(
            'juloserver.fraud_score.monnai_services.MonnaiRepository.'
            '_construct_payload_for_address_verification_and_device_detail')
        self.mock_construct_payload = self.patch_construct_payload_for_address_verification_and_device_detail.start()

        self.patch_validate_request_data = mock.patch(
            'juloserver.fraud_score.monnai_services.MonnaiRepository._validate_request_data',
            return_value=None)
        self.mock_validate_request_data = self.patch_validate_request_data.start()

        self.patch_fetch_insight = mock.patch(
            'juloserver.fraud_score.monnai_services.MonnaiRepository.fetch_insight',
            return_value=None,
        )
        self.mock_fetch_insight = self.patch_fetch_insight.start()

        self.mock_monnai_client = mock.MagicMock()
        self.mock_redis_client = mock.MagicMock()
        self.mock_redis_client.get.return_value = 'access_token'
        self.monnai_repository = MonnaiRepository(self.mock_monnai_client, self.mock_redis_client)

        self.customer_with_advertising_id = CustomerFactory(advertising_id='advertising-id')
        self.application = ApplicationJ1Factory(customer=self.customer_with_advertising_id)
        self.address_geolocation = AddressGeolocationFactory(
            application=self.application, latitude=-1.23, longitude=123.456
        )

    def tearDown(self):
        self.mock_construct_payload.stop()
        self.mock_validate_request_data.stop()
        self.mock_fetch_insight.stop()
        super().tearDown()

    def test_valid_payload_data_monnai_insight_request_created(self):
        self.application.update_safely(mobile_phone_1='082167912345')
        self.mock_construct_payload.return_value = {
            'eventType': 'ACCOUNT_UPDATED',
            'locationCoordinates': {
                'latitude': -1.23,
                'longitude': -123.456,
            },
            'phoneNumber': '082167912345',
        }

        expected_application_id = self.application.id
        expected_package_list = ['DEVICE_DETAILS']
        expected_tsp_name = "TELKOMSEL"
        expected_payload = {
            'eventType': 'ACCOUNT_UPDATED',
            'locationCoordinates': {
                'latitude': -1.23,
                'longitude': -123.456,
            },
            'phoneNumber': '082167912345',
        }

        result = self.monnai_repository.fetch_insight_for_address_verification_and_device_detail(
            self.application,
            ['ADDRESS_VERIFICATION', 'DEVICE_DETAILS'],
            "TELKOMSEL",
            self.application.mobile_phone_1,
        )
        mock_fetch_insight_package_application_id = self.mock_fetch_insight.call_args[0][0]
        mock_fetch_insight_package_tsp_name = self.mock_fetch_insight.call_args[0][1]
        mock_fetch_insight_package_parameter = self.mock_fetch_insight.call_args[0][2]
        mock_fetch_insight_payload_parameter = self.mock_fetch_insight.call_args[0][3]

        self.assertEqual(mock_fetch_insight_package_application_id, expected_application_id)
        self.assertEqual(mock_fetch_insight_package_tsp_name, expected_tsp_name)
        self.assertEqual(mock_fetch_insight_package_parameter, expected_package_list)
        self.assertEqual(mock_fetch_insight_payload_parameter, expected_payload)
        self.assertIsNone(result)

    def test_broken_function_process_raises_exception(self):
        self.mock_construct_payload.side_effect = Exception('Test exception')

        with self.assertRaises(Exception):
            self.monnai_repository.fetch_insight_for_address_verification_and_device_detail(
                self.application)

        self.mock_validate_request_data.assert_not_called()
        self.mock_fetch_insight.assert_not_called()


class TestFetchAndStorePhoneInsights(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(
            mobile_phone_1='0812345678', customer=CustomerFactory()
        )
        self.repository = MonnaiRepository(mock.MagicMock(), mock.MagicMock())
        self.repository.fetch_insight_with_response = mock.MagicMock()
        self.repository._store_phone_basic_insight = mock.MagicMock()
        self.repository._store_phone_social_insight = mock.MagicMock()
        self.repository._handle_insight_errors = mock.MagicMock()

    def test_fetch_and_store_phone_insights_success(self):
        # Setup mock response
        response = Response()
        response.status_code = 200
        response._content = json.dumps({'data': {'phone': {'basic': {}, 'social': {}}}}).encode(
            'utf-8'
        )
        self.repository.fetch_insight_with_response.return_value = response

        # Execute the method under test
        result = self.repository.fetch_and_store_phone_insights(self.application)

        # Assert conditions
        self.assertTrue(result)
        self.repository._store_phone_basic_insight.assert_called_once()
        self.repository._store_phone_social_insight.assert_called_once()
        self.repository._handle_insight_errors.assert_not_called()

    def test_fetch_and_store_phone_insights_api_failure(self):
        # Setup API to throw an exception
        self.repository.fetch_insight_with_response.side_effect = Exception("API Error")

        # Execute the method under test
        result = self.repository.fetch_and_store_phone_insights(self.application)

        # Assert conditions
        self.assertFalse(result)
        self.repository._store_phone_basic_insight.assert_not_called()
        self.repository._store_phone_social_insight.assert_not_called()
        self.repository._handle_insight_errors.assert_called_once()

    def test_fetch_and_store_phone_insights_handle_error(self):
        # Assume response is unsuccessful
        response = Response()
        response.status_code = 500
        self.repository.fetch_insight_with_response.return_value = response

        # Cause the response to raise an HTTP error
        with mock.patch.object(response, 'raise_for_status', side_effect=HTTPError):
            result = self.repository.fetch_and_store_phone_insights(self.application)

        # Assert conditions
        self.assertFalse(result)
        self.repository._store_phone_basic_insight.assert_not_called()
        self.repository._store_phone_social_insight.assert_not_called()
        self.repository._handle_insight_errors.assert_called_once()


class TestFetchAndStoreEmailInsights(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(email='user@example.com', customer=CustomerFactory())
        self.mon_client = mock.MagicMock()
        self.redis_client = mock.MagicMock()
        self.repository = MonnaiRepository(self.mon_client, self.redis_client)
        self.repository._store_email_basic_insight = mock.MagicMock()
        self.repository._store_email_social_insight = mock.MagicMock()
        self.repository._handle_insight_errors = mock.MagicMock()

    def test_fetch_and_store_email_insights_api_failure(self):
        # Setup API to throw an exception
        self.mon_client.fetch_insight_with_response.side_effect = Exception("API Error")

        # Execute the method under test
        result = self.repository.fetch_and_store_email_insights(self.application)

        # Assert conditions
        self.assertFalse(result)
        self.repository._store_email_basic_insight.assert_not_called()
        self.repository._store_email_social_insight.assert_not_called()
        self.repository._handle_insight_errors.assert_called_once()


class TestStoreAddressVerificationAndDeviceDetailResult(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(
            mobile_phone_1='0812345678', customer=CustomerFactory()
        )

        self.mock_monnai_client = mock.MagicMock()
        self.mock_redis_client = mock.MagicMock()
        self.mock_redis_client.get.return_value = 'access_token'
        self.monnai_repository = MonnaiRepository(self.mock_monnai_client, self.mock_redis_client)

        self.tsp_name = "TELKOMSEL"
        self.response_json = {
            "data": {
                "address": {
                    "basic": None,
                    "verification": {
                        "closestDistance": {
                            "min": 0.0,
                            "max": 1493.982
                        },
                        "locationConfidence": "High",
                        "cellTowerDensity": "Very High",
                        "cellTowerRanking": 4,
                        "locationType": "NIGHT"
                    }
                },
                "device": {
                    "deviceRecords": []
                }
            },
            "meta": {
                "inputPhoneNumber": "+62812345678",
                "cleansedPhoneNumber": "+62812345678",
                "referenceId": "01HQ9WTKEXA7HVD0WBCRNXGFW4",
                "inputDeviceIds": [
                    "47557af3-145c-47a3-b967-8670cb739637"
                ],
                "requestedPackages": [
                    "ADDRESS_VERIFICATION",
                    "DEVICE_DETAILS"
                ],
                "inputLocationCoordinates": {
                    "latitude": "-6.36036036036036",
                    "longitude": "107.254769124057"
                }
            },
            "errors": []
        }

    @mock.patch('juloserver.fraud_score.models.TelcoLocationResult.objects.create')
    def test_store_address_verification(self, mock_telco_location_result):
        packages = ["ADDRESS_VERIFICATION"]
        result = self.monnai_repository.store_address_verification_and_device_detail_result(
            self.application.id, self.tsp_name, packages, self.response_json
        )
        mock_telco_location_result.return_value = TelcoLocationResultFactory(
            fraud_telco_location_result=1
        )
        mock_telco_location_result.assert_called()
        self.assertIsNone(result)

    @mock.patch('juloserver.fraud_score.models.MaidResult.objects.create')
    def test_store_device_detail(self, mock_maid_result):
        packages = ["DEVICE_DETAILS"]
        result = self.monnai_repository.store_address_verification_and_device_detail_result(
            self.application.id, self.tsp_name, packages, self.response_json
        )
        mock_maid_result.return_value = MaidResultFactory(maid_result_id=1)
        mock_maid_result.assert_called()
        self.assertIsNone(result)
