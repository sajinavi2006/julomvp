import time
import requests
from django.conf import settings
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR
from juloserver.julolog.julolog import JuloLog
from juloserver.ocr.exceptions import (
    OCRInternalClientException,
    OCRBadRequestException,
    OCRInternalServerException,
    OCRServerTimeoutException,
)

logger = JuloLog(__name__)


class NewOCRClient(object):
    class API:
        SUBMIT_KTP = '/api/v1/ktp'

    def __init__(self, host, session=None, timeout=10, retry=None):
        self.host = host
        self.session = session or requests.Session()
        self.timeout = timeout
        self.response = {}
        self.retry = retry or 3
        self._headers = {}

    def construct_headers(self, unique_id, confident_threshold):
        self._headers = {'Content-Type': 'application/json', 'x-unique-id': str(unique_id)}
        if confident_threshold:
            self._headers['x-confidence-threshold-default'] = str(confident_threshold)

        return self._headers

    def submit_ktp_ocr(self, data, unique_id, confident_threshold=None):
        self.construct_headers(unique_id, confident_threshold)
        result = self.request(
            api=self.API.SUBMIT_KTP,
            data=data,
            method='POST',
        )

        return result

    def request(
        self,
        api,
        method,
        data=None,
        retry_count=None,
        timeout=None,
    ):
        timeout = timeout or self.timeout
        url = self.host + api
        if not retry_count:
            retry_count = self.retry
        while retry_count > 0:
            retry_count -= 1
            try:
                start_time = time.time()
                if method == 'GET':
                    if data:
                        response = self.session.get(
                            url, params=data, timeout=timeout, headers=self._headers
                        )
                    else:
                        response = self.session.get(url, timeout=timeout, headers=self._headers)
                elif method == 'POST':
                    response = self.session.post(
                        url, json=data, timeout=self.timeout, headers=self._headers
                    )
                else:
                    raise NotImplementedError('method {} not found'.format(method))

                elapsed = int((time.time() - start_time) * 1000)

                try:
                    self.response = response.json()
                except ValueError as error:
                    raise OCRInternalClientException(str(error))

                logger.info(
                    'ktp_ocr_response|url={}, headers={}, response_status={}, elapsed={}'.format(
                        url, self._headers, response.status_code, elapsed
                    )
                )

                if response.status_code == HTTP_200_OK:
                    return self.response

                if (
                    HTTP_400_BAD_REQUEST
                    <= int(response.status_code)
                    < HTTP_500_INTERNAL_SERVER_ERROR
                ):
                    raise OCRBadRequestException(
                        {
                            'response': self.response,
                            'status': response.status_code,
                        }
                    )

                raise OCRInternalServerException(
                    {'response': self.response, 'status': response.status_code}
                )

            except (
                requests.exceptions.ConnectTimeout,
                requests.exceptions.Timeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as error:
                logger.error(
                    "ktp_ocr_request_timeout|url={}, headers={}, error={}".format(
                        url, self._headers, str(error)
                    )
                )
                if retry_count <= 0:
                    raise OCRServerTimeoutException(str(error))
            except (
                OCRInternalClientException,
                OCRInternalServerException,
                OCRBadRequestException,
            ) as error:
                raise error
            except Exception as error:
                logger.error(
                    "dot_client_request_exception|url={}, headers={}, error={}".format(
                        url, self._headers, str(error)
                    )
                )
                if retry_count <= 0:
                    raise OCRInternalClientException(str(error))


def get_ocr_client():
    return NewOCRClient(settings.OCR_URL)
