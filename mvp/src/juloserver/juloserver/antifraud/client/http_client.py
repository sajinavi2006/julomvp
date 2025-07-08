import requests
import logging
from builtins import object
from requests.models import Response


logger = logging.getLogger(__name__)


class HTTPClient(object):
    def __init__(
        self,
        base_url: str = None,
    ):
        if not base_url:
            raise ValueError('missing configuration "base_url"')

        if base_url.endswith("/"):
            base_url = base_url[:-1]
        self.base_url = base_url

    def _construct_url(self, path: str) -> str:
        if path.startswith("/"):
            path = path[1:]
        return "{}/{}".format(self.base_url, path)

    def get(
        self,
        path: str,
        params: dict = None,
        headers: dict = None,
    ) -> Response:

        if headers is None:
            headers = {}

        url = self._construct_url(path)

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
                    "action": "antifraud_client.get",
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "error": e,
                }
            )
            raise e

        return response

    def post(
        self,
        path: str,
        data: dict,
        headers: dict = None,
    ) -> Response:

        if headers is None:
            headers = {}

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
                    "action": "antifraud_client.post",
                    "url": url,
                    "headers": headers,
                    "data": data,
                    "error": e,
                }
            )
            raise e

        return response
