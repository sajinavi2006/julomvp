import requests
from requests.exceptions import ConnectTimeout, Timeout, ReadTimeout, ConnectionError
import time
from django.conf import settings
from rest_framework.status import HTTP_200_OK
from juloserver.julolog.julolog import JuloLog
from juloserver.personal_data_verification.exceptions import (
    DukcapilFRClientError,
    DukcapilFRServerError,
    DukcapilFRServerTimeout,
)
from juloserver.julo.models import FeatureSetting

logger = JuloLog(__name__)


class DukcapilFRClient:
    class API:
        FR = '/api/face-recognition/dukcapil/{}/CALL_FR'

    class InternalStatus:
        SERVER_BUSY = 5000
        ACCOUNT_NOT_FOUND = 5001
        RATE_LIMIT_REQUEST = 5002
        IP_NOT_ALLOW = 5003
        INVALID_PARAM = 5004
        INVALID_THRESHOLD = 5005
        DATA_DECRYPTION_FAIL = 5006
        INVALID_DATA_FORMAT = 6006
        SERVER_BUSY_1 = 6012
        SERVER_BUSY_2 = 6014
        CANT_NOT_PROCESS_IMAGE = 6015
        SUCCESS = 6018
        IMAGE_NOT_MATCH = 6019
        NIK_NOT_FOUND = 6020
        WRONG_PASSWORD = 9002

    def __init__(self, host, credential_id, session=None, timeout=60, retry=3):
        self.host = host
        self.session = session or requests.Session()
        self.credential_id = credential_id
        self._headers = {}
        self.timeout = timeout
        self.retry = retry

    @property
    def headers(self):
        if not self._headers:
            self._headers = {
                'Content-Type': 'application/json',
            }

        return self._headers

    def face_recognition(self, request_data):
        url = self.API.FR.format(self.credential_id)
        response = self.request(url, 'POST', request_data)

        return response

    def request(self, api, method, data, timeout=None, retry_count=None, success_statuses=None):
        if success_statuses is None:
            success_statuses = [HTTP_200_OK]
        fs_timeout = (
            FeatureSetting.objects.filter(feature_name='dukcapil_fr_threshold')
            .last()
            .parameters.get('j1')
            .get('timeout', 60)
        )
        timeout = timeout or self.timeout or fs_timeout
        url = self.host + api
        if not retry_count:
            retry_count = self.retry
        while retry_count > 0:
            retry_count -= 1
            try:
                start_time = time.time()
                logger.info(
                    {
                        "message": 'start_dukcapil_fr',
                        "transaction_id": data.get('transactionId'),
                    }
                )
                if method == 'POST':
                    response = self.session.post(
                        url, json=data, timeout=timeout, headers=self.headers
                    )
                else:
                    raise NotImplementedError('method not allowed')
                elapsed = int((time.time() - start_time) * 1000)
                logger.info(
                    {
                        "message": 'finish_dukcapil_fr',
                        "transaction_id": data.get('transactionId'),
                        "elapsed": elapsed,
                    }
                )
                try:
                    result = response.json()
                    logger.info(
                        {
                            "message": 'Dukcapil_FR_response',
                            "transaction_id": data.get('transactionId'),
                            "url": url,
                            "response": result,
                            "status_code": response.status_code,
                        }
                    )
                except Exception as error:
                    logger.info(
                        {
                            "message": 'Dukcapil_FR_failed_convert',
                            "transaction_id": data.get('transactionId'),
                            "url": url,
                            "response": str(response),
                            "status_code": response.status_code,
                        }
                    )
                    raise DukcapilFRClientError(str(error))

                if response.status_code not in success_statuses:
                    logger.info(
                        {
                            "message": 'Dukcapil_FR_status_not_expected',
                            "transaction_id": data.get('transactionId'),
                            "url": url,
                            "response": str(response),
                            "status_code": response.status_code,
                        }
                    )
                    raise DukcapilFRServerError(
                        {'response': result, 'status': response.status_code, 'elapsed': elapsed}
                    )
                return result
            except (ConnectTimeout, Timeout, ReadTimeout, ConnectionError) as error:
                logger.error(
                    {
                        "message": 'dukcapil_request_timeout',
                        "transaction_id": data.get('transactionId'),
                        "url": url,
                        "error": str(error),
                    }
                )
                if retry_count <= 0:
                    raise DukcapilFRServerTimeout(str(error))
            except (DukcapilFRClientError, DukcapilFRServerError, NotImplementedError) as error:
                raise error
            except Exception as error:
                logger.info(
                    {
                        "message": 'dot_client_request_exception',
                        "transaction_id": data.get('transactionId'),
                        "url": url,
                        "error": str(error),
                    }
                )
                if retry_count <= 0:
                    raise DukcapilFRClientError(str(error))


def get_dukcapil_fr_client():
    return DukcapilFRClient(
        host=settings.DUKCAPIL_FR_HOST, credential_id=settings.DUKCAPIL_FR_CREDENTIAL_ID
    )
