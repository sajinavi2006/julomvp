from copy import deepcopy
import logging
import datetime
import requests
from django.conf import settings
from requests import Response
from typing import Union

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.fraud_score.clients.juicy_score_client import get_juicy_score_client
from juloserver.fraud_score.models import JuicyScoreResult
from juloserver.julo.models import Application, ApplicationHistory, FeatureSetting
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.application_flow.services import JuloOneService
from juloserver.fraud_security.binary_check import process_fraud_binary_check
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pii_vault.constants import PiiSource

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def get_juicy_score_repository():
    return JuicyScoreRepository(
        juicy_score_client=get_juicy_score_client()
    )


def check_application_exist_in_result(application_id: int) -> bool:
    """
    Check if application id is exist on JuicyScoreResult.
    Args:
        application_id (int): application_id to be checked.

    Returns:
        bool: True if application_id is exist. False otherwise.
    """
    juicy_score_result = JuicyScoreResult.objects.filter(
        application_id=application_id
    ).last()
    if juicy_score_result:
        return True
    return False


def check_api_limit_exceeded(feature_setting: FeatureSetting) -> bool:
    """
    Check if juicy score api has exceed limit.
    Args:
        feature_setting (FeatureSetting): FeatureSetting object to be checked.

    Returns:
        bool: True if feature has exceeded. False otherwise.
    """
    if feature_setting.parameters['use_threshold']:
        threshold = feature_setting.parameters['threshold']
        number_of_rows = JuicyScoreResult.objects.count()
        if threshold and (number_of_rows >= threshold):
            return True
    return False


def is_eligible_for_juicy_score(application: Application) -> bool:
    """
    Check if application eligible for juicy score.
    Args:
        application (Application): Application object to be checked.

    Returns:
        bool: True if application is eligible. False otherwise.
    """
    if not check_application_is_julo_one(application):
        return False
    if not check_application_after_105(application):
        return False
    if not is_not_c_score(application):
        return False
    if not check_application_pass_binary_check(application):
        return False

    return True


def check_application_is_julo_one(application: Application) -> bool:
    result = application.is_julo_one_product()
    if not result:
        logger.info({
            'action': 'juicy_score_services check_application_is_julo_one',
            'application_id': application.id,
            'message': 'application is not julo one'
        })
    return result


def check_application_after_105(application: Application) -> bool:
    result = False
    app_history_105 = ApplicationHistory.objects.filter(
        application=application, status_new=ApplicationStatusCodes.FORM_PARTIAL
    ).last()

    if app_history_105:
        result = True
    if not result:
        logger.info(
            {
                'action': 'juicy_score_services check_application_after_105',
                'application_id': application.id,
                'message': 'application is not pass x105',
            }
        )
    return result


def is_not_c_score(application: Application) -> bool:
    result = not JuloOneService.is_c_score(application)
    if not result:
        logger.info({
            'action': 'juicy_score_services check_application_pass_c_score',
            'application_id': application.id,
            'message': 'application is not pass c score'
        })
    return result


def check_application_pass_binary_check(application: Application) -> bool:
    is_pass_fraud_check, fail_fraud_check_handler = process_fraud_binary_check(
        application, source='juicy_score|check_application_pass_binary_check'
    )
    if not is_pass_fraud_check:
        logger.info({
            'action': 'juicy_score_services check_application_pass_binary_check',
            'application_id': application.id,
            'message': 'application is not pass binary check'
        })
    return is_pass_fraud_check


class JuicyScoreRepository:

    account_id = settings.JUICY_SCORE_ACCOUNT_ID
    TIMEZONE_UTC7 = 7
    TIMEZONE_UTC3 = 3
    API_VERSION = "15"
    CHANNEL = "PHONE_APP"
    PHONE_COUNTRY = "62"
    TYPE_RESPONSE = "json"

    def __init__(self, juicy_score_client):
        self.juicy_score_client = juicy_score_client

    def fetch_get_score_api_result(self, data_request: dict, application: Application):
        """
        Fetch the get score API result from Juicy Score. Then store the result in our database.
        We will store these data to ops.juicy_score_result
        """
        try:
            request_data = self.construct_request_data(data_request, application)
            raw_request = deepcopy(request_data)
            juicy_score_result = JuicyScoreResult.objects.create(
                application_id=data_request['application_id'],
                customer_id=data_request['customer_id'],
                session_id=data_request['session_id'],
                raw_request=raw_request,
            )
            if settings.ENVIRONMENT != 'prod':
                logger.info(
                    {
                        'action': 'juicy_score service fetch_get_score_api_result',
                        'env': settings.ENVIRONMENT,
                        'request_data': request_data,
                    }
                )
            started_time = datetime.datetime.now()
            response = self.juicy_score_client.fetch_get_score_api(request_data)
            response.raise_for_status()
            latency = (datetime.datetime.now() - started_time).total_seconds()
            juicy_score_result.update_safely(
                http_status_code=response.status_code,
                latency=latency,
                raw_response=self.parse_response(response)
            )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout
        ) as e:
            latency = (datetime.datetime.now() - started_time).total_seconds()
            updated_fields = {
                'latency': latency,
                'raw_response': str(e),
            }
            if hasattr(e, 'response') and e.response is not None:
                updated_fields.update({'http_status_code': e.response.status_code})
            juicy_score_result.update_safely(**updated_fields)
            sentry_client.captureException()
            logger.exception({
                'action': 'juicy_score service fetch_get_score_api_result',
                'message': 'HTTP requests exception detected.',
                'error': str(e),
            })
        except Exception as e:
            latency = (datetime.datetime.now() - started_time).total_seconds()
            updated_fields = {
                'latency': latency,
                'raw_response': str(e),
            }
            if hasattr(e, 'response') and e.response is not None:
                updated_fields.update({'http_status_code': e.response.status_code})
            juicy_score_result.update_safely(
                latency=latency,
                raw_response=str(e)
            )
            sentry_client.captureException()
            logger.exception({
                'action': 'juicy_score service fetch_get_score_api_result',
                'message': 'HTTP requests exception detected.',
                'error': str(e),
            })

    def construct_request_data(self, data_request: dict, application: Application):
        """
        Construct the request data to be sent to Juicy Score.
        Args:
            application (Application): Application object.
        Returns:
            dict: data request for params.
        """
        application_id = data_request['application_id']
        customer_xid = data_request['customer_xid']
        session_id = data_request['session_id']

        phone_prefix = ""
        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application], ['mobile_phone_1']
        )[0]
        if detokenized_application.mobile_phone_1:
            phone_prefix = detokenized_application.mobile_phone_1[1:7]

        return {
            "account_id": self.account_id,
            "client_id": customer_xid,
            "session_id": session_id,
            "channel": self.CHANNEL,
            "time_utc3": self.get_date_time(self.TIMEZONE_UTC3),
            "version": self.API_VERSION,
            "time_local": self.get_date_time(self.TIMEZONE_UTC7),
            "ph_country": self.PHONE_COUNTRY,
            "phone": phone_prefix,
            "application_id": application_id,
            "time_zone": str(self.TIMEZONE_UTC7),
            "response_content_type": self.TYPE_RESPONSE
        }

    def get_date_time(self, timezone: int) -> str:
        """
        Get date and time according to the specified time zone,
        in a specified format ex 03.05.2024 17:38:49.
        Args:
            timezone(int): time difference with UTC.
        Returns:
            str: formatted date and time.
        """
        offset = datetime.timezone(datetime.timedelta(hours=timezone))
        datetime_format = '%d.%m.%Y %H:%M:%S'
        datetime_formatted = datetime.datetime.now(offset).strftime(datetime_format)
        return datetime_formatted

    def parse_response(self, response: Response) -> Union[dict, str]:
        """
        parse the response from an HTTP request into JSON format.
        If cannot be parsed as JSON, it return response as text.
        Args:
            response (Response): Response object from requests.
        Returns:
            Union[dict, str]: parsed response.
        """
        try:
            raw_response = response.json()
            return raw_response
        except requests.exceptions.JSONDecodeError:
            return response.text
