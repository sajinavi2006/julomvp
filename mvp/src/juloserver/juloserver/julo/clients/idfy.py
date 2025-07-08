from builtins import str
from builtins import object
import logging
import requests
from django.conf import settings
from juloserver.julo.exceptions import JuloException
from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

logger = logging.getLogger(__name__)


class IDfyTimeout(JuloException):
    pass


class IDfyServerError(JuloException):
    pass


class IDfyProfileCreationError(JuloException):
    pass


class IDfyGetProfileError(JuloException):
    pass


class IDfyApplicationNotAllowed(JuloException):
    pass


class IDfyOutsideOfficeHour(JuloException):
    pass


class IDFyGeneralMessageError(JuloException):
    pass


class IDfyApiClient(object):
    def __init__(self, app_api_key, config_id, base_url):
        self.app_api_key = app_api_key
        self.config_id = config_id
        self.base_url = base_url
        self.response_url = None

    def create_profile(
        self,
        application_xid,
        first_name="Test",
        last_name="JULO",
        email=None,
        mobile_number=None,
    ):
        data = {
            "reference_id": str(application_xid),
            "config": {
                "id": self.config_id

            },
            "data": {
                "name": {
                    "first_name": first_name,
                    "last_name": last_name,
                },
                "additional_details": [
                ]
            },
            "email_ids": [
                email,
            ],
            "mobile_numbers": [
                mobile_number,
            ],
            "payload": {
            }
        }

        relative_url = '/sync/profiles'
        headers = {
            'api-key': self.app_api_key,
            'Content-Type': 'application/json'
        }
        url = ''.join([self.base_url, relative_url])
        response = requests.request("POST", url, json=data, headers=headers)
        if 400 <= response.status_code < 500:
            message = 'Profile creation failed: {} - {}'.format(response.status_code, response.reason)
            logger.warning({'action': 'IDfyApiClient >> create_profile', 'message': message, 'application_xid': application_xid})
            if response.status_code == 422:
                raise IDfyProfileCreationError(message)
            raise IDfyTimeout
        if response.status_code >= 500:
            message = 'Idfy Server error {} - {}'.format(response.status_code, response.reason)
            logger.warning({'action': 'IDfyApiClient >> create_profile', 'message': message, 'application_xid': application_xid})
            raise IDfyServerError(message)

        logger.info(
            {
                "action": "IDfyApiClient >> create_profile",
                "url": url,
                "data": data,
                "response": response.json(),
            }
        )

        return response.json()

    def get_profile_details(self, profile_id, reference_id=None):
        """
            Method for fetching profile details
        """

        relative_path = f'/profiles/{profile_id}'

        headers = {
            'api-key': self.app_api_key,
            'Content-Type': 'application/json'
        }
        url = ''.join([self.base_url, relative_path])
        logger.info({'action': 'IDfyApiClient >> get_profile_details', 'url': url, 'profile_id': profile_id})
        response = requests.get(url, headers=headers)
        logger.info({'message': 'Response from IDfyApiClient >> get_profile_details', 'response': response.json()})
        if HTTP_400_BAD_REQUEST <= response.status_code < HTTP_500_INTERNAL_SERVER_ERROR:
            message = 'Profile details retrieval failed: {} - {}'.format(response.status_code, response.reason)
            logger.warning(
                {'message': message, 'profile_id': profile_id})
            raise IDfyGetProfileError(message)
        if response.status_code >= HTTP_500_INTERNAL_SERVER_ERROR:
            message = 'IDfy Server error {} - {}'.format(response.status_code, response.reason)
            logger.warning(
                {'message': message, 'profile_id': profile_id})
            raise IDfyServerError(message)

        return response.json()


def get_idfy_client():
    """
        Initialise an IDfy Client
    """
    idfy_client = IDfyApiClient(
        app_api_key=settings.IDFY_API_KEY,
        config_id=settings.IDFY_CONFIG_ID,
        base_url=settings.IDFY_BASE_URL
    )
    return idfy_client
