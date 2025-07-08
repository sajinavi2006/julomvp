import json
import logging
from datetime import timedelta
from functools import wraps
from hashlib import md5
import time

from django.conf import settings
from requests import Response
from requests.exceptions import (
    ConnectTimeout,
    ConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)
from dateutil.parser import parse
from django.utils.dateparse import parse_datetime, parse_date

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.fraud_score.clients.monnai_client import (
    MonnaiClient,
    NotAuthenticated,
    get_monnai_client,
)
from juloserver.fraud_score.constants import (
    RequestErrorType,
    MonnaiConstants,
    FeatureNameConst as FraudScoreFeatureNameConst,
)
from juloserver.fraud_score.exceptions import IncompleteRequestData
from juloserver.fraud_score.models import (
    MonnaiInsightRawResult,
    MonnaiInsightRequest,
    MonnaiPhoneBasicInsight,
    MonnaiPhoneSocialInsight,
    MonnaiEmailBasicInsight,
    MonnaiEmailSocialInsight,
    TelcoLocationResult,
    MaidResult,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import InvalidPhoneNumberError
from juloserver.julo.models import (
    Application,
    AddressGeolocation,
    FeatureSetting,
    ApplicationHistory,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.device_ip_history import get_application_submission_ip_history
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.services2.redis_helper import RedisHelper
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import format_valid_e164_indo_phone_number
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


def get_monnai_feature_setting():
    return FeatureSettingHelper(FeatureNameConst.MONNAI_FRAUD_SCORE)


def monnai_enabled_wrapper(func):
    """
    Decorator to check if monnai_fraud_score is enabled or not.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        feature_setting = get_monnai_feature_setting()
        if feature_setting.is_active:
            return func(*args, **kwargs)
        return None

    return wrapper


class MonnaiRepository:
    PACKAGE_SCOPES = {
        'PHONE_BASIC': 'insights/phone_basic',
        'PHONE_SOCIAL': 'insights/phone_social',
        'EMAIL_BASIC': 'insights/email_basic',
        'EMAIL_SOCIAL': 'insights/email_social',
        'IP_BASIC': 'insights/ip_basic',
        'IDENTITY_ENRICHMENT': 'insights/identity_enrichment',
        'IDENTITY_CORRELATION': 'insights/identity_correlation',
        'DEVICE_DETAILS': 'insights/device_details',
        'ADDRESS_VERIFICATION': 'insights/address_verification',
    }

    def __init__(self, monnai_client: MonnaiClient, redis_client: RedisHelper):
        self.monnai_client = monnai_client
        self.redis_client = redis_client
        self.mock_setting = None
        self.mock_status_code = None
        self.mock_json_response = None
        self.retry_on_error = False

    def set_mock(self, key_param: str):
        if settings.ENVIRONMENT == 'prod':
            return

        self.mock_setting = FeatureSetting.objects.get_or_none(
            feature_name=FraudScoreFeatureNameConst.MOCK_MONNAI_INSIGHT,
        )
        if not self.mock_setting:
            return
        if not self.mock_setting.is_active:
            return
        if not self.mock_setting.parameters:
            return

        self.mock_status_code = self.mock_setting.parameters.get('status_code')
        if self.mock_status_code and not isinstance(self.mock_status_code, list):
            self.mock_status_code = [
                self.mock_status_code,
                self.mock_status_code,
                self.mock_status_code,
            ]
        self.mock_json_response = self.mock_setting.parameters.get(key_param)

    def set_retry_on_error(self, retry_on_error):
        self.retry_on_error = retry_on_error

    def authenticate(self, scopes: list = None):
        """
        Authenticate to monnai API to obtain the access_token.
        The access_token is cache in redis until 30 seconds before it expired.
        The expiry duration is came from monnai authentication API.

        Returns:
            str: The access_token string.
        """
        if scopes is None:
            scopes = list(self.PACKAGE_SCOPES.values())

        suffix_key = md5('_'.join(scopes).encode()).hexdigest()
        cache_key = 'fraud_score::monnai::access_token::{}'.format(suffix_key)

        access_token = self.redis_client.get(cache_key)
        if access_token:
            self.monnai_client.set_access_token(access_token)
            return access_token

        access_token, expire_in_secs = self.monnai_client.fetch_access_token(scopes=scopes)

        self.redis_client.set(cache_key, access_token, timedelta(seconds=expire_in_secs - 30))
        return access_token

    def _construct_application_submission_data(self, application) -> dict:
        """
        Construct the request payload for application submission data.
        TODO: After POC is done. Must check whether this function will be needed,
            if not then we should delete it.

        Args:
            application (Application): the Application object

        Returns:
            dict: The payload dictionary.
        """
        logger_data = {
            'action': 'MonnaiRepository::_construct_application_submission_data',
            'application_id': application.id,
        }
        try:
            phone_number = format_valid_e164_indo_phone_number(application.mobile_phone_1)
        except InvalidPhoneNumberError as e:
            phone_number = None
            logger.warning({
                'message': "Invalid phone number error",
                'exception': str(e),
                'mobile_phone_1': application.mobile_phone_1,
                **logger_data,
            }, exc_info=True)

        device_ip_history = get_application_submission_ip_history(application)
        advertising_id = application.customer.advertising_id

        payload = {
            'phoneNumber': phone_number,
            'phoneDefaultCountryCode': 'ID',
            'email': application.email,
            'ipAddress': device_ip_history.ip_address if device_ip_history else None,
            'deviceIds': [advertising_id] if advertising_id else [],
            'countryCode': 'ID',
        }

        self._validate_request_data(payload)

        return payload

    def _validate_request_data(self, payload: dict) -> None:
        """
        Raise IncompleteRequestData if there either email, phone_number, or ipAddress are empty.
        Args:
            payload (dict): The payload data

        Raises:
            IncompleteRequestData
        """
        if not all(payload.values()):
            raise IncompleteRequestData("Some Monnai request data are missing", payload)

    def fetch_insight(self, application_id: int, tsp_name: str, packages: list, payloads: dict):
        # This function for address verification and device detail only
        response = None
        try:
            scopes = [self.PACKAGE_SCOPES[package] for package in packages]
            self.authenticate(scopes)

            response_json = {}
            # for testing purpose only
            mock_monnai_fs = FeatureSettingHelper('monnai_telco_maid_location_mock')
            if mock_monnai_fs.is_active:
                logger.info({
                    'action': 'MonnaiRequest:fetch_insight',
                    'application_id': application_id,
                    'message': 'hit response from mock'
                })
                response_json = mock_monnai_fs.params
            else:
                logger.info(
                    {
                        'action': 'MonnaiRequest:fetch_insight',
                        'application_id': application_id,
                        'message': 'hit monnai api for {}'.format(str(scopes)),
                    }
                )
                response = self.monnai_client.fetch_insight(
                    packages, payloads, application_id=application_id
                )
                response.raise_for_status()

                # Process 200 success Request
                response_json = response.json()

            errors = response_json['errors']
            if errors != []:
                logger.error({
                    'action': 'MonnaiRequest:fetch_insight',
                    'application_id': application_id,
                    'message': 'monnai got error',
                    'error': str(errors)
                })
                return

            self.store_address_verification_and_device_detail_result(
                application_id, tsp_name, packages, response_json
            )

        except Exception as e:
            if isinstance(e, HTTPError) or isinstance(e, NotAuthenticated):
                error_type = RequestErrorType.HTTP_ERROR
            elif isinstance(e, ConnectTimeout):
                error_type = RequestErrorType.CONNECT_TIMEOUT_ERROR
            elif isinstance(e, ReadTimeout):
                error_type = RequestErrorType.READ_TIMEOUT_ERROR
            elif isinstance(e, ConnectionError):
                error_type = RequestErrorType.CONNECTION_ERROR
            elif isinstance(e, RequestException):
                error_type = RequestErrorType.OTHER_ERROR
            else:
                error_type = RequestErrorType.UNKNOWN_ERROR

            logger.error({
                'action': 'MonnaiRequest:fetch_insight',
                'error_type': error_type,
                'error': str(e),
                'application_id': application_id,
                'response_status': response.status_code if response is not None else None,
                'response_data': response.text if response is not None else None,
                'request_data': payloads,
            })
            raise

    def store_address_verification(
        self,
        application_id: int,
        tsp_name: str,
        response_json: dict,
        location: AddressGeolocation
    ) -> None:
        telco_location_result_data = {
            'application_id': application_id,
            'vendor': 'monnai',
            'tsp': tsp_name,
            'input_lat': location.latitude if location else '0',
            'input_long': location.longitude if location else '0'
        }
        address = response_json["data"].get("address")
        address_verification = address.get("verification") if address else None
        if not address or not address_verification:
            TelcoLocationResult.objects.create(**telco_location_result_data)
            logger.warning({
                'action': 'MonnaiRequest:\
                    store_address_verification_and_device_detail_result',
                'application_id': application_id,
                'message': "address or address_verification is none"
            })
            return

        is_phone_number_correct = address_verification.get("closestDistance", None)
        if not is_phone_number_correct:
            logger.warning({
                'action': 'MonnaiRequest:\
                    store_address_verification_and_device_detail_result',
                'application_id': application_id,
                'message': "phone number is not correct"
            })
            return

        closest_dist = address_verification.get('closestDistance')
        telco_location_result_data = {
            **telco_location_result_data,
            'cell_tower_ranking': address_verification.get('cellTowerRanking'),
            'cell_tower_density': address_verification.get('cellTowerDensity'),
            'location_type': address_verification.get('locationType'),
            'dist_min': closest_dist.get('min') if closest_dist else None,
            'dist_max': closest_dist.get('max') if closest_dist else None,
            'location_confidence': address_verification.get('locationConfidence')
        }
        TelcoLocationResult.objects.create(**telco_location_result_data)

    def store_device_detail(
        self, application_id: int, response_json: dict, location: AddressGeolocation
    ):
        maid_result_data = {
            'application_id': application_id,
            'input_lat': location.latitude if location else '0',
            'input_long': location.longitude if location else '0'
        }
        device = response_json["data"].get("device")
        device_records = device.get("deviceRecords") if device else None
        device_location = device_records[0].get('location') if device_records else None

        if not device or not device_records or not device_location:
            MaidResult.objects.create(**maid_result_data)
            logger.warning({
                'action': 'MonnaiRequest:\
                    store_address_verification_and_device_detail_result',
                'application_id': application_id,
                'message': "device or device_records is none"
            })
            return

        day_loc = device_location.get('dayLocation')
        night_loc = device_location.get('nightLocation')
        most_seen_loc = device_location.get('mostSeenLocation')
        maid_result_data = {
            **maid_result_data,
            'day_lat': day_loc.get('latitude') if day_loc else None,
            'day_long': day_loc.get('longitude') if day_loc else None,
            'night_lat': night_loc.get('latitude') if night_loc else None,
            'night_long': night_loc.get('longitude') if night_loc else None,
            'most_seen_lat': most_seen_loc.get('latitude') if most_seen_loc else None,
            'most_seen_long': most_seen_loc.get('longitude') if most_seen_loc else None
        }
        MaidResult.objects.create(**maid_result_data)

    def store_address_verification_and_device_detail_result(
        self, application_id: int, tsp_name: str, packages: list, response_json: dict
    ) -> None:
        """
        Store response from monnai to fraud_telco_location_result table
        (for ADDRESS_VERIFICATION package) and monnai_maid_result
        (for DEVICE_DETAILS package)

        Args:
            application (Application): the Application object
            tsp_name (str): telco service provider name
            packages (list): list of package
            response_json (dict): response from monnai api

        Returns:
            None
        """
        location = AddressGeolocation.objects.filter(
            application_id=application_id
        ).last()
        for package in packages:
            if package == "ADDRESS_VERIFICATION":
                self.store_address_verification(application_id, tsp_name, response_json, location)

            if package == "DEVICE_DETAILS":
                self.store_device_detail(application_id, response_json, location)

    def __fetch_insight(
        self, packages: list, payloads: dict, n_retry: int = None, application_id: int = None
    ):
        response = None
        if self.mock_setting and self.mock_setting.is_active:
            response = Response()
            if self.mock_status_code and n_retry and isinstance(n_retry, int):
                try:
                    response.status_code = self.mock_status_code[n_retry]
                except Exception:
                    response.status_code = self.mock_status_code[-1]
            elif self.mock_status_code:
                response.status_code = self.mock_status_code[0]
            else:
                response.status_code = 200
            response._content = json.dumps(self.mock_json_response).encode('utf-8')
            return response

        scopes = [self.PACKAGE_SCOPES[package] for package in packages]
        self.authenticate(scopes)
        return self.monnai_client.fetch_insight(packages, payloads, application_id=application_id)

    def fetch_insight_with_retry(
        self, monnai_request: MonnaiInsightRequest, packages: list, payloads: dict, n_retry: int = 0
    ):
        application_id = None
        if monnai_request and monnai_request.application:
            application_id = monnai_request.application.id

        response = self.__fetch_insight(packages, payloads, n_retry, application_id=application_id)
        if 500 <= response.status_code < 600 and n_retry < 3:
            time.sleep(60 * (2**n_retry))
            logger.info(
                {
                    'action': 'fetch_insight_with_retry',
                    'status_code': response.status_code,
                    'n_retry': n_retry + 1,
                    'application_id': monnai_request.application.id,
                }
            )
            response = self.fetch_insight_with_retry(
                monnai_request, packages, payloads, n_retry + 1, application_id=application_id
            )
        return response

    def fetch_insight_with_response(
        self, monnai_request: MonnaiInsightRequest, packages: list, payloads: dict
    ):
        response = None
        try:
            if self.retry_on_error:
                response = self.fetch_insight_with_retry(monnai_request, packages, payloads)
            else:
                application_id = None
                if monnai_request and monnai_request.application:
                    application_id = monnai_request.application.id

                response = self.__fetch_insight(packages, payloads, application_id=application_id)

            self._fill_request_with_response(monnai_request, response)
            response.raise_for_status()

            # Process 200 success request
            response_json = response.json()
            monnai_request.transaction_id = response_json.get('meta', {}).get('referenceId')
            monnai_request.save()
            MonnaiInsightRawResult.objects.create(
                monnai_insight_request=monnai_request,
                raw=response.text,
            )
        except Exception as e:
            self._handle_response_error(e, monnai_request, response, payloads)
            raise e  # Re-raise the exception after handling
        return response

    def _handle_response_error(self, e, monnai_request, response, payloads):
        if isinstance(e, HTTPError) or isinstance(e, NotAuthenticated):
            if e.response is not None:
                self._fill_request_with_response(monnai_request, e.response)
            monnai_request.error_type = RequestErrorType.HTTP_ERROR
        elif isinstance(e, ConnectTimeout):
            monnai_request.error_type = RequestErrorType.CONNECT_TIMEOUT_ERROR
        elif isinstance(e, ReadTimeout):
            monnai_request.error_type = RequestErrorType.READ_TIMEOUT_ERROR
        elif isinstance(e, ConnectionError):
            monnai_request.error_type = RequestErrorType.CONNECTION_ERROR
        elif isinstance(e, RequestException):
            monnai_request.error_type = RequestErrorType.OTHER_ERROR
        else:
            monnai_request.error_type = RequestErrorType.UNKNOWN_ERROR

        monnai_request.save()
        logger.error(
            {
                'action': 'MonnaiRequest:fetch_insight',
                'error': str(e),
                'monnai_request_id': monnai_request.id,
                'response_status': response.status_code if response is not None else None,
                'response_data': response.text if response is not None else None,
                'request_data': payloads,
            }
        )

    def _fill_request_with_response(
        self,
        monnai_request: MonnaiInsightRequest,
        response: Response,
    ) -> MonnaiInsightRequest:
        monnai_request.response_time = int(response.elapsed.total_seconds() * 1000)
        monnai_request.response_code = response.status_code

        if response.status_code == 400:
            errors = response.json().get('errors')
            if errors and len(errors) > 0:
                monnai_request.monnai_error_code = errors[0].get('code')

        return monnai_request

    def _construct_payload_for_address_verification_and_device_detail(
        self, application: Application, raw_phone_number: str, packages: list
    ):
        """
        Constructs the body parameter requested by Monnai's Insight API depending on the selected
        package/scope.
        TODO: Crude implementation for POC, near identical as
            _construct_application_submission_data.
            Consider payload construction by package function on final implementation.
        Args:
            application (Application): Application object.

        Returns:
            Dict: The payload for Monnai's Insight API.
        """
        logger_data = {
            'action': 'MonnaiRepository::'
                      '_construct_payload_for_address_verification_and_device_detail',
            'application_id': application.id,
        }
        try:
            phone_number = format_valid_e164_indo_phone_number(raw_phone_number)
        except InvalidPhoneNumberError as e:
            phone_number = None
            logger.warning({
                'message': 'Invalid phone number error',
                'exception': str(e),
                'mobile_phone_1': application.mobile_phone_1,
                **logger_data,
            }, exc_info=True)

        advertising_id = application.customer.advertising_id
        location_coordinates = AddressGeolocation.objects.by_application(application).last()

        payload = {
            'eventType': 'ACCOUNT_UPDATE',
            'packages': packages,
            'countryCode': 'ID',
            'phoneDefaultCountryCode': 'ID',
            'phoneNumber': phone_number,
            'locationCoordinates': {
                'latitude': location_coordinates.latitude,
                'longitude': location_coordinates.longitude,
            },
            'deviceIds': [advertising_id] if advertising_id else [],
            'cleansingFlag': True,
        }
        consent_details = self._get_consent_details(application)
        if consent_details != {}:
            payload[MonnaiConstants.CONSENT_DETAILS] = consent_details
        else:
            payload['packages'] = [MonnaiConstants.DEVICE_DETAILS]

        return payload

    def _additional_payload_for_address_verification(
        self, payload: dict, application: Application
    ) -> dict:
        """
        Add additional params for address_verification package.
        Args:
            application (Application): Application object.

        Returns:
            Dict: The payload for Monnai's Insight API that has been updated.
        """
        if not application.address_street_num:
            return payload

        additional_payload = {
            "address": {
                "addressLine1": application.address_street_num,
                "addressLine2": None,
                "addressLine3": self._format_address_line3(
                    application.address_kelurahan, application.address_kecamatan
                ),
                "addressLine4": self._format_address_line4(
                    application.address_kabupaten, application.address_provinsi
                ),
                "city": application.address_kabupaten,
                "state": None,
                "postalCode": application.address_kodepos,
                "country": "Indonesia"
            }
        }
        payload.update(additional_payload)
        return payload

    def _format_address_line3(self, sub_district: str = None, district: str = None) -> str:
        """
        Format the address based on the provided sub-district and district.

        Args:
            sub_district (str, optional): Name of the sub-district (kelurahan).
            district (str, optional): Name of the district (kecamatan).

        Returns:
            str: A formatted address string.
        """
        if sub_district and district:
            return "{}, Kecamatan {}".format(sub_district, district)
        elif sub_district:
            return sub_district
        elif district:
            return "Kecamatan {}".format(district)
        return None

    def _format_address_line4(self, city: str = None, province: str = None) -> str:
        """
        Format the address based on the provided city and province.

        Args:
            city (str, optional): Name of the city (kota).
            province (str, optional): Name of the province (provinsi).

        Returns:
            str: A formatted address string.
        """
        if city and province:
            return "{}, {}".format(city, province)
        elif city:
            return city
        elif province:
            return province
        return None

    def fetch_insight_for_address_verification_and_device_detail(
        self, application: Application, packages: list, tsp_name: str, phone_number: str
    ) -> None:
        """
        Fetch and store Monnai's Insight API for ADDRESS_VERIFICATION and DEVICE_DETAIL
        packages data.

        Args:
            application (Application): Application object.

        Returns:
            None
        """
        payload = self._construct_payload_for_address_verification_and_device_detail(
            application, phone_number, packages
        )
        self._validate_request_data(payload)
        if (MonnaiConstants.CONSENT_DETAILS not in payload) and\
                (MonnaiConstants.ADDRESS_VERIFICATION in packages):
            packages.remove(MonnaiConstants.ADDRESS_VERIFICATION)

        if MonnaiConstants.ADDRESS_VERIFICATION in packages:
            payload = self._additional_payload_for_address_verification(payload, application)

        if not packages:
            logger.info(
                {
                    'message': 'packages is empty',
                    'function': 'fetch_insight_for_address_verification_and_device_detail',
                    'application_id': application.id,
                }
            )
            return

        self.fetch_insight(application.id, tsp_name, packages, payload)

    def fetch_and_store_phone_insights(self, application: Application, source='') -> bool:
        try:
            phone_number = format_valid_e164_indo_phone_number(application.mobile_phone_1)
        except InvalidPhoneNumberError as e:
            phone_number = None
            logger.warning(
                {
                    'message': "Invalid phone number error",
                    'exception': str(e),
                    'mobile_phone_1': application.mobile_phone_1,
                    'application_id': application.id,
                },
                exc_info=True,
            )

        advertising_id = application.customer.advertising_id
        payload = {
            'eventType': 'ACCOUNT_CREATION',
            'phoneNumber': phone_number,
            'phoneDefaultCountryCode': 'ID',
            'packages': ['PHONE_BASIC', 'PHONE_SOCIAL'],
            'deviceIds': [advertising_id] if advertising_id else [],
            'cleansingFlag': True,
        }

        monnai_request = MonnaiInsightRequest(
            application=application,
            customer_id=application.customer_id,
            action_type=payload['eventType'],
            phone_number=payload['phoneNumber'],
        )
        response = None
        try:
            logger.info(
                {
                    'message': source,
                    'function': 'fetch_and_store_phone_insight',
                    'application_id': application.id,
                }
            )

            response = self.fetch_insight_with_response(
                monnai_request, ['PHONE_BASIC', 'PHONE_SOCIAL'], payload
            )
            response.raise_for_status()
            response_json = response.json()

            phone_data = (response_json.get('data', {}) or {}).get('phone', {}) or {}
            phone_basic_data = phone_data.get('basic', {}) or {}
            phone_social_data = phone_data.get('social', {}) or {}

            self._store_phone_basic_insight(
                application, monnai_request, phone_basic_data, response_json
            )
            self._store_phone_social_insight(application, monnai_request, phone_social_data)

            logger.info("Monnai Phone Insights saved for Request ID: {0}".format(monnai_request.id))
            return True

        except Exception as e:
            logger.error(
                "Error fetching and storing phone insights: {0}".format(str(e)), exc_info=True
            )
            self._handle_insight_errors(
                e, monnai_request, response, payload, 'fetch_and_store_phone_insights'
            )
            return False

    def _store_phone_basic_insight(
        self, application, monnai_request, phone_basic_data, response_json
    ):
        try:
            MonnaiPhoneBasicInsight.objects.create(
                application=application,
                monnai_insight_request=monnai_request,
                phone_disposable=phone_basic_data.get('phoneDisposable', False),
                active=phone_basic_data.get('active', 'UNKNOWN') != 'NO',
                activation_date=self._format_date(phone_basic_data.get('activationDate')),
                active_since_x_days=phone_basic_data.get('activeSinceXDays', 0),
                sim_type=phone_basic_data.get('simType', 'Unknown'),
                phone_number_age=phone_basic_data.get('phoneNumberAge', 0),
                phone_number_age_description=phone_basic_data.get('phoneNumberAgeDescription', ''),
                phone_tenure=phone_basic_data.get('phoneTenure', 0),
                last_deactivated=self._format_date(phone_basic_data.get('lastDeactivated')),
                is_spam=phone_basic_data.get('isSpam', False),
                raw_response=json.dumps(response_json),
            )
        except Exception as ex:
            logger.error("Error processing phone basic data:{0}".format(str(ex)))

    def _store_phone_social_insight(self, application, monnai_request, phone_social_data):
        try:
            summary = phone_social_data.get('summary', {}) or {}
            profiles = phone_social_data.get('profiles', {}) or {}

            MonnaiPhoneSocialInsight.objects.create(
                application=application,
                monnai_insight_request=monnai_request,
                registered_profiles=summary.get('registeredProfiles', 0),
                registered_email_provider_profiles=summary.get(
                    'registeredEmailProviderProfiles', 0
                ),
                registered_ecommerce_profiles=summary.get('registeredEcommerceProfiles', 0),
                registered_social_media_profiles=summary.get('registeredSocialMediaProfiles', 0),
                registered_professional_profiles=summary.get('registeredProfessionalProfiles', 0),
                registered_messaging_profiles=summary.get('registeredMessagingProfiles', 0),
                last_activity=parse_datetime(summary.get('lastActivity'))
                if summary.get('lastActivity')
                else None,
                number_of_names_returned=summary.get('numberOfNamesReturned', 0),
                number_of_photos_returned=summary.get('numberOfPhotosReturned', 0),
                messaging_telegram_registered=profiles.get('messaging', {})
                .get('telegram', {})
                .get('registered', False),
                messaging_whatsapp_registered=profiles.get('messaging', {})
                .get('whatsapp', {})
                .get('registered', False),
                messaging_viber_registered=profiles.get('messaging', {})
                .get('viber', {})
                .get('registered', False),
                messaging_kakao_registered=profiles.get('messaging', {})
                .get('kakao', {})
                .get('registered', False),
                messaging_skype_registered=profiles.get('messaging', {})
                .get('skype', {})
                .get('registered', False),
                messaging_ok_registered=profiles.get('messaging', {})
                .get('ok', {})
                .get('registered', False),
                messaging_zalo_registered=profiles.get('messaging', {})
                .get('zalo', {})
                .get('registered', False),
                messaging_line_registered=profiles.get('messaging', {})
                .get('line', {})
                .get('registered', False),
                messaging_snapchat_registered=profiles.get('messaging', {})
                .get('snapchat', {})
                .get('registered', False),
                email_provider_google_registered=profiles.get('emailProvider', {})
                .get('google', {})
                .get('registered', False),
                social_media_facebook_registered=profiles.get('socialMedia', {})
                .get('facebook', {})
                .get('registered', False),
                social_media_twitter_registered=profiles.get('socialMedia', {})
                .get('twitter', {})
                .get('registered', False),
                social_media_instagram_registered=profiles.get('socialMedia', {})
                .get('instagram', {})
                .get('registered', False),
                raw_response=json.dumps(phone_social_data),
            )
        except Exception as ex:
            logger.error("Error processing phone social data:{0}".format(str(ex)))

    def fetch_and_store_email_insights(self, application: Application) -> bool:
        try:
            detokenized_applications = detokenize_pii_antifraud_data(
                PiiSource.APPLICATION, [application]
            )[0]
            email = (
                detokenized_applications.email
            )  # Assuming the email is stored in the application object
        except AttributeError as e:
            logger.warning(
                {
                    'message': "Invalid email error",
                    'exception': str(e),
                    'application_id': application.id,
                },
                exc_info=True,
            )
            return False

        payload = {
            'eventType': 'ACCOUNT_CREATION',
            'email': email,
            'packages': ['EMAIL_BASIC', 'EMAIL_SOCIAL'],
        }

        monnai_request = MonnaiInsightRequest(
            application=application,
            customer_id=application.customer_id,
            action_type=payload['eventType'],
            email_address=payload['email'],
        )
        response = None
        try:
            response = self.fetch_insight_with_response(
                monnai_request, ['EMAIL_BASIC', 'EMAIL_SOCIAL'], payload
            )
            response.raise_for_status()
            response_json = response.json()

            email_data = (response_json.get('data', {}) or {}).get('email', {}) or {}
            email_basic_data = email_data.get('basic', {}) or {}
            email_social_data = email_data.get('social', {}) or {}

            self._store_email_basic_insight(application, monnai_request, email_basic_data)
            self._store_email_social_insight(application, monnai_request, email_social_data)

            logger.info("Monnai Email Insights saved for Request ID:{0}".format(monnai_request.id))
            return True

        except Exception as e:
            logger.error(
                "Error fetching and storing email insights:{0}".format(str(e)), exc_info=True
            )
            self._handle_insight_errors(
                e, monnai_request, response, payload, 'fetch_and_store_email_insights'
            )
            return False

    def _store_email_basic_insight(self, application, monnai_request, email_basic_data):
        domain_details = email_basic_data.get('domainDetails', {}) or {}
        breach = email_basic_data.get('breach', {}) or {}
        try:
            MonnaiEmailBasicInsight.objects.create(
                application=application,
                monnai_insight_request=monnai_request,
                deliverable=email_basic_data.get('deliverable', False),
                domain_name=domain_details.get('domainName')
                if domain_details.get('domainName')
                else None,
                tld=domain_details.get('tld') if domain_details.get('tld') else None,
                creation_time=parse_datetime(domain_details.get('creationTime'))
                if domain_details.get('creationTime')
                else None,
                update_time=parse_datetime(domain_details.get('updateTime'))
                if domain_details.get('updateTime')
                else None,
                expiry_time=parse_datetime(domain_details.get('expiryTime'))
                if domain_details.get('expiryTime')
                else None,
                registered=domain_details.get('registered', False),
                company_name=domain_details.get('companyName'),
                registrar_name=domain_details.get('registrarName'),
                disposable=domain_details.get('disposable', False),
                free_provider=domain_details.get('freeProvider', False),
                dmarc_compliance=domain_details.get('dmarcCompliance', False),
                spf_strict=domain_details.get('spfStrict', False),
                suspicious_tld=domain_details.get('suspiciousTld', False),
                website_exists=domain_details.get('websiteExists', False),
                accept_all=domain_details.get('acceptAll', False),
                custom=domain_details.get('custom', False),
                breaches=breach.get('breaches', []),
                is_breached=breach.get('isBreached', False),
                no_of_breaches=breach.get('noOfBreaches', 0),
                first_breach=parse_date(breach.get('firstBreach'))
                if breach.get('firstBreach')
                else None,
                last_breach=parse_date(breach.get('lastBreach'))
                if breach.get('lastBreach')
                else None,
                raw_response=json.dumps(email_basic_data),
            )
        except Exception as ex:
            logger.error("Error processing email basic data:{0}".format(str(ex)))

    def _store_email_social_insight(self, application, monnai_request, email_social_data):
        try:
            summary = email_social_data.get('summary', {}) or {}
            profiles = email_social_data.get('profiles', {}) or {}

            registered_profiles = summary.get('registeredProfiles', 0)
            registered_consumer_electronics_profiles = summary.get(
                'registeredConsumerElectronicsProfiles', 0
            )
            registered_email_provider_profiles = summary.get('registeredEmailProviderProfiles', 0)
            registered_ecommerce_profiles = summary.get('registeredEcommerceProfiles', 0)
            registered_social_media_profiles = summary.get('registeredSocialMediaProfiles', 0)
            registered_messaging_profiles = summary.get('registeredMessagingProfiles', 0)
            registered_professional_profiles = summary.get('registeredProfessionalProfiles', 0)
            registered_entertainment_profiles = summary.get('registeredEntertainmentProfiles', 0)
            registered_travel_profiles = summary.get('registeredTravelProfiles', 0)
            age_on_social = summary.get('ageOnSocial', None)
            number_of_names_returned = summary.get('numberOfNamesReturned', 0)
            number_of_photos_returned = summary.get('numberOfPhotosReturned', 0)

            facebook_registered = (
                profiles.get('socialMedia', {}).get('facebook', {}).get('registered', False)
            )
            instagram_registered = (
                profiles.get('socialMedia', {}).get('instagram', {}).get('registered', False)
            )
            twitter_registered = (
                profiles.get('socialMedia', {}).get('twitter', {}).get('registered', False)
            )
            quora_registered = (
                profiles.get('socialMedia', {}).get('quora', {}).get('registered', False)
            )
            github_registered = (
                profiles.get('professional', {}).get('github', {}).get('registered', False)
            )
            linkedin_registered = (
                profiles.get('professional', {}).get('linkedin', {}).get('registered', False)
            )
            linkedin_url = profiles.get('professional', {}).get('linkedin', {}).get('url', None)
            linkedin_name = profiles.get('professional', {}).get('linkedin', {}).get('name', None)
            linkedin_company = (
                profiles.get('professional', {}).get('linkedin', {}).get('company', None)
            )

            MonnaiEmailSocialInsight.objects.create(
                application=application,
                monnai_insight_request=monnai_request,
                registered_profiles=registered_profiles,
                registered_consumer_electronics_profiles=registered_consumer_electronics_profiles,
                registered_email_provider_profiles=registered_email_provider_profiles,
                registered_ecommerce_profiles=registered_ecommerce_profiles,
                registered_social_media_profiles=registered_social_media_profiles,
                registered_messaging_profiles=registered_messaging_profiles,
                registered_professional_profiles=registered_professional_profiles,
                registered_entertainment_profiles=registered_entertainment_profiles,
                registered_travel_profiles=registered_travel_profiles,
                age_on_social=age_on_social,
                number_of_names_returned=number_of_names_returned,
                number_of_photos_returned=number_of_photos_returned,
                facebook_registered=facebook_registered,
                instagram_registered=instagram_registered,
                twitter_registered=twitter_registered,
                quora_registered=quora_registered,
                github_registered=github_registered,
                linkedin_registered=linkedin_registered,
                linkedin_url=linkedin_url,
                linkedin_name=linkedin_name,
                linkedin_company=linkedin_company,
                raw_response=json.dumps(email_social_data),
            )
        except Exception as ex:
            logger.error("Error processing email social data:{0}".format(str(ex)))

    def _handle_insight_errors(self, e, monnai_request, response, payload, action):
        error_type = 'UNKNOWN_ERROR'
        if isinstance(e, HTTPError) or isinstance(e, NotAuthenticated):
            error_type = 'HTTP_ERROR'
        elif isinstance(e, ConnectTimeout):
            error_type = 'CONNECT_TIMEOUT_ERROR'
        elif isinstance(e, ReadTimeout):
            error_type = 'READ_TIMEOUT_ERROR'
        elif isinstance(e, ConnectionError):
            error_type = 'CONNECTION_ERROR'
        elif isinstance(e, RequestException):
            error_type = 'OTHER_ERROR'

        monnai_request.error_type = error_type
        monnai_request.save()

        logger.error(
            {
                'action': action,
                'error': str(e),
                'monnai_request_id': monnai_request.id,
                'response_status': response.status_code if response else None,
                'response_data': response.text if response else None,
                'request_data': payload,
            }
        )
        raise e

    def _format_date(self, date_str):
        if not date_str:
            return None
        try:
            parsed_date = parse(date_str)
            formatted_date = parsed_date.date().isoformat()
            return formatted_date
        except Exception as e:
            logger.error("Failed to parse date '{0}': {1}".format(date_str, e), exc_info=True)
            return None

    def _get_consent_details(self, application: Application) -> dict:
        consent_info = {}
        last_application = application.customer.get_active_or_last_application
        if (
            last_application
            and last_application.is_julo_one()
            and last_application.is_term_accepted
            and last_application.is_verification_agreed
        ):
            consent_timestamp = self._get_consent_timestamp(last_application)
            if consent_timestamp:
                consent_info['consentId'] = str(application.customer.id)
                consent_info['consentTimestamp'] = consent_timestamp
                consent_info['consentType'] = MonnaiConstants.APP

        return consent_info

    def _get_consent_timestamp(self, application: Application) -> str:
        application_history = ApplicationHistory.objects.filter(
            application=application,
            status_old=ApplicationStatusCodes.FORM_CREATED,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
        ).last()
        return (
            str(application_history.cdate.strftime(MonnaiConstants.TIMESTAMPFORMAT))
            if application_history
            else None
        )


def get_monnai_repository() -> MonnaiRepository:
    """
    Get the monnai repository.
    Returns:
        MonnaiRepository
    """
    return MonnaiRepository(
        monnai_client=get_monnai_client(),
        redis_client=get_redis_client(),
    )
