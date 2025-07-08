from copy import deepcopy
import json
import logging
from typing import Tuple

import requests
from django.conf import settings
from requests import Response
from requests.exceptions import (
    JSONDecodeError,
    HTTPError,
)
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.antifraud.services.monnai_log import MonnaiRequestLogService
from juloserver.fraud_score.constants import FeatureNameConst

logger = logging.getLogger(__name__)


def get_monnai_client():
    return MonnaiClient(
        auth_base_url=settings.MONNAI_AUTH_BASE_URL,
        insight_base_url=settings.MONNAI_INSIGHT_BASE_URL,
        client_id=settings.MONNAI_CLIENT_ID,
        client_secret=settings.MONNAI_CLIENT_SECRET,
    )


class NotAuthenticated(Exception):
    def __init__(self, msg="Unauthorized access", response=None):
        super(NotAuthenticated, self).__init__(msg)
        self.response = response


class MonnaiClient:
    """
    Class to communicate with Monnai API:
    https://monnai.gitbook.io/monnai-docs/api-reference/insights
    """
    AUTHENTICATION_ENDPOINT = '/oauth2/token'
    INSIGHT_ENDPOINT = '/api/insights'

    def __init__(self, auth_base_url, insight_base_url, client_id, client_secret):
        self.auth_base_url = auth_base_url
        self.insight_base_url = insight_base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = None
        self.is_using_mock_server = False
        self.override_url_using_mock_server()

    def set_access_token(self, access_token):
        self._access_token = access_token

    def check_authenticated(self):
        if not self._access_token:
            raise NotAuthenticated("Not authenticated")

    def fetch_access_token(self, scopes: list) -> Tuple[str, int]:
        """
        Fetch authentication's access token
        Args:
            scopes (list[str]): List of scope names.
                https://monnai.gitbook.io/monnai-docs/api-reference/overview#insights

        Returns:
            Tuple[str, int]: Return a tuple of access_token and expired in seconds.
        """
        url = self.auth_base_url + self.AUTHENTICATION_ENDPOINT
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        }
        payload = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials',
            'scope': " ".join(scopes)
        }
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()

        try:
            response_json = response.json()
            access_token = response_json['access_token']
            expired_in = int(response_json['expires_in'])
        except (JSONDecodeError, KeyError, ValueError) as e:
            raise HTTPError("Unexpected body format.", response=response) from e

        self.set_access_token(access_token)
        return access_token, expired_in

    def fetch_insight(
        self, packages: list, payload: dict, reference_id: str = None, application_id: int = None
    ) -> Response:
        """
        Fetch insight API.

        Args:
            packages (list[str]): List of package string must be align with the scope in the auth.
                https://monnai.gitbook.io/monnai-docs/api-reference/overview
            payload (dict): Payload of the insight data.
            reference_id (Optional[str]): Reference ID.

        Returns:
            Response: Response object.
        """
        self.check_authenticated()

        url = self.insight_base_url + self.INSIGHT_ENDPOINT
        headers = {
            'Authorization': 'Bearer {}'.format(self._access_token),
            'Content-Type': 'application/vnd.monnai.v1.1+json',
        }
        if reference_id:
            headers['x-reference-id'] = reference_id

        payload.update(packages=packages)
        if settings.ENVIRONMENT != 'prod':
            # Log the prepared request details
            logger.info("Prepared URL: %s" % url)
            logger.info("Prepared Headers: %s" % json.dumps(headers, indent=4))
            logger.info("Prepared Payload: %s" % json.dumps(payload, indent=4))

            if self.is_using_mock_server:
                # always sort the package since the mock server will provide
                # just one combination of package order
                _packages = deepcopy(packages)
                _packages.sort()
                headers['x-packages-mock'] = ','.join(packages)

        # Send the request
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 401:
            raise NotAuthenticated(response=response)

        # Store log to fraud db
        monnaisvc = MonnaiRequestLogService.get_monnai_log_svc(
            response=response, application_id=application_id, packages=packages
        )
        if monnaisvc:
            monnaisvc.send()

        return response

    def override_url_using_mock_server(self):
        if settings.ENVIRONMENT == 'prod':
            return

        fs = FeatureSettingHelper(FeatureNameConst.MOCK_MONNAI_URL)
        if not fs.is_active:
            return

        self.auth_base_url = fs.get('MONNAI_AUTH_BASE_URL', self.auth_base_url)
        _insight_base_url = fs.get('MONNAI_INSIGHT_BASE_URL')
        if _insight_base_url:
            self.is_using_mock_server = True
            self.insight_base_url = _insight_base_url
            logger.info(
                {
                    'action': 'mock_monnai_url',
                    'MONNAI_AUTH_BASE_URL': self.auth_base_url,
                    'MONNAI_INSIGHT_BASE_URL': self.insight_base_url,
                }
            )
