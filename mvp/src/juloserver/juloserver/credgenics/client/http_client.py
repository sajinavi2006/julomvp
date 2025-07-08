import requests
import logging
from builtins import object
from requests.models import Response
from typing import Union

from juloserver.credgenics.constants.transport import (
    Header,
)

logger = logging.getLogger(__name__)


class HTTPClient(object):
    def __init__(
        self,
        base_url: str = None,
        auth_token: str = None,
        company_id: str = None,
    ):
        if not base_url:
            raise ValueError('missing configuration "base_url"')
        if not auth_token:
            raise ValueError('missing configuration "auth_token"')
        if not company_id:
            raise ValueError('missing configuration "company_id"')

        self.base_url = base_url
        self.auth_token = auth_token
        self.company_id = company_id

    def _construct_url(self, path: str, extra_param: str = None) -> str:
        url = "{}/{}?company_id={}".format(self.base_url, path, self.company_id)
        if extra_param is not None:
            url += "&{}".format(extra_param)
        return url

    def get(
        self, path: str, params: dict = None, headers: dict = None, extra_param: str = None
    ) -> Response:

        if headers is None:
            headers = {}

        headers[Header.AUTH_TOKEN] = self.auth_token

        url = self._construct_url(path, extra_param=extra_param)

        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(
                {
                    "action": "credgenics_client.get",
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "error": e,
                }
            )
            return e

        return response

    def post(
        self,
        path: str,
        data: dict,
        headers: dict = None,
    ) -> Response:

        if headers is None:
            headers = {}

        headers[Header.AUTH_TOKEN] = self.auth_token

        url = self._construct_url(path)

        try:
            response = requests.post(
                url,
                json=data,
                headers=headers,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(
                {
                    "action": "credgenics_client.post",
                    "url": url,
                    "headers": headers,
                    "data": data,
                    "error": e,
                }
            )
            return None

        return response

    def patch(
        self, path: str, data: dict, headers: dict = None, extra_param: str = None
    ) -> Union[Response, None]:

        if headers is None:
            headers = {}

        headers[Header.AUTH_TOKEN] = self.auth_token
        url = self._construct_url(path, extra_param)

        try:
            response = requests.patch(
                url,
                json=data,
                headers=headers,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(
                {
                    "action": "credgenics_client.patch",
                    "url": url,
                    "headers": headers,
                    "data": data,
                    "error": e,
                }
            )

        return response
