import logging
import time

import requests
from django.conf import settings
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from juloserver.julocore.cache_client import get_default_cache, get_redis_cache
from juloserver.liveness_detection.constants import (
    DEFAULT_API_RETRY,
    CacheKeys,
    LivenessCheckType,
    LivenessVendor,
    ActiveLivenessMethod,
)
from juloserver.liveness_detection.exceptions import (
    DotCoreClientError,
    DotCoreClientInternalError,
    DotCoreServerError,
    DotCoreServerTimeout,
    DotClientError,
    DotClientInternalError,
    DotServerError,
    DotServerTimeout,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessVendorResult,
    PassiveLivenessVendorResult,
)

logger = logging.getLogger(__name__)


class DotCoreClient:
    class API:
        ACTIVE_LIVENESS_CHECK = '/api/v6/face/check-liveness-active'
        PASSIVE_LIVENESS_CHECK = '/api/v6/face/detect'
        SERVER_INFO = '/api/v6/actuator/info'

    def __init__(self, host, session=None, timeout=10, retry=None):
        self.host = host
        self.session = session or requests.Session()
        self.timeout = timeout
        self.response = {}
        self.elapsed = None
        self.vendor_result = None
        self.retry = retry or DEFAULT_API_RETRY

    def check_active_liveness(self, segments: list, configs: dict) -> tuple:
        request_data = {
            'segments': segments,
            'minValidSegmentCount': configs['valid_segment_count'],
            'faceSizeRatio': {'min': configs['min_face_ratio'], 'max': configs['max_face_ratio']},
        }
        result, elapsed = self.request(
            api=self.API.ACTIVE_LIVENESS_CHECK,
            method='POST',
            data=request_data,
            retry_count=configs['timeout_retry'],
            timeout=configs['timeout'],
        )

        return result, elapsed, self.vendor_result

    def check_passive_liveness(self, image: str, configs: dict) -> tuple:
        request_data = {
            'image': {
                'data': image,
                'faceSizeRatio': {
                    'min': configs['min_face_ratio'],
                    'max': configs['max_face_ratio'],
                },
            },
            'template': configs['template'],
            'cropImage': configs['crop_image'],
            'facialFeatures': configs['facial_features'],
            'icaoAttributes': configs['icao_attributes'],
            'faceAttributes': configs['face_attributes'],
            'cropImageWithRemovedBackground': configs['crop_image_with_removed_background'],
        }
        result, elapsed = self.request(
            api=self.API.PASSIVE_LIVENESS_CHECK,
            method='POST',
            data=request_data,
            retry_count=configs['timeout_retry'],
            timeout=configs['timeout'],
        )

        return result, elapsed, self.vendor_result

    def get_api_info(self, configs: dict) -> dict:
        default_cache = get_default_cache()
        result = default_cache.get(CacheKeys.API_INFO['key'], {})
        retry_count, timeout = None, None
        if configs:
            retry_count = configs.get('timeout_retry')
            timeout = configs.get('timeout')
        if not result:
            result, elapsed = self.request(
                api=self.API.SERVER_INFO,
                data=None,
                method='GET',
                retry_count=retry_count,
                timeout=timeout,
            )
            default_cache.set(CacheKeys.API_INFO['key'], result, CacheKeys.API_INFO['timeout'])

        return result

    def request(self, api, data, method, retry_count=None, timeout=None):
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
                        response = self.session.get(url, params=data, timeout=timeout)
                    else:
                        response = self.session.get(url, timeout=timeout)
                else:
                    response = self.session.post(url, json=data, timeout=self.timeout)
                elapsed = int((time.time() - start_time) * 1000)

                try:
                    self.response = response.json()
                    self.capture_response(api)
                except ValueError as error:
                    raise DotCoreClientInternalError(str(error))

                if response.status_code == HTTP_200_OK:
                    return self.response, elapsed

                error_message = 'dot_client_request_failed|api={}, status={}, response={}'.format(
                    url, response.status_code, response.text
                )
                logger.warning(error_message)
                if HTTP_400_BAD_REQUEST <= response.status_code < HTTP_500_INTERNAL_SERVER_ERROR:
                    raise DotCoreClientError(
                        {
                            'response': self.response,
                            'status': response.status_code,
                            'elapsed': elapsed,
                        }
                    )

                raise DotCoreServerError(
                    {'response': self.response, 'status': response.status_code, 'elapsed': elapsed}
                )

            except (
                requests.exceptions.ConnectTimeout,
                requests.exceptions.Timeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as error:
                logger.exception(
                    "dot_client_request_timeout|api={}, error={}".format(api, str(error))
                )
                if retry_count <= 0:
                    raise DotCoreServerTimeout(str(error))
            except (DotCoreClientError, DotCoreServerError) as error:
                raise error
            except Exception as error:
                logger.exception(
                    "dot_client_request_exception|api={}, error={}".format(api, str(error))
                )
                if retry_count <= 0:
                    raise DotCoreClientInternalError(str(error))

    def capture_response(self, api: str):
        if api == self.API.ACTIVE_LIVENESS_CHECK:
            self.vendor_result = ActiveLivenessVendorResult.objects.create(
                vendor_name=LivenessVendor.INNOVATRICS,
                raw_response=self.response,
                raw_response_type=LivenessCheckType.ACTIVE,
            )
        elif api == self.API.PASSIVE_LIVENESS_CHECK:
            self.vendor_result = PassiveLivenessVendorResult.objects.create(
                vendor_name=LivenessVendor.INNOVATRICS,
                raw_response=self.response,
                raw_response_type=LivenessCheckType.PASSIVE,
            )


def get_dot_core_client() -> DotCoreClient:
    dot_core_client = DotCoreClient(settings.DOT_API_BASE_URL)

    return dot_core_client


class DotDigitalIdentityClient:
    class API:
        CREATE_CUSTOMER = '/api/v1/customers'
        CREATE_CUSTOMER_SELFIE = '/api/v1/customers/{}/selfie'  # use the neutral image
        CREATE_CUSTOMER_LIVENESS = '/api/v1/customers/{}/liveness'
        UPLOAD_IMAGE = '/api/v1/customers/{}/liveness/selfies'  # assertion=SMILE
        EVALUATE = '/api/v1/customers/{}/liveness/evaluation'
        SERVER_INFO = '/api/v1/info'
        DELETE_CUSTOMER = '/api/v1/customers/{}'
        CREATE_CUSTOMER_LIVENESS_RECORD_CHALLENGE = (
            '/api/v1/customers/{}/liveness/records/challenge'
        )
        UPLOAD_CUSTOMER_LIVENESS_RECORD = '/api/v1/customers/{}/liveness/records'
        INSPECT_CUSTOMER = '/api/v1/customers/{}/inspect'

    class UploadImageAssertionType:
        SMILE = 'SMILE'
        NEUTRAL = 'NEUTRAL'
        PASSIVE = 'NONE'

    class EvaluateType:
        SMILE = 'SMILE_LIVENESS'
        PASSIVE = 'PASSIVE_LIVENESS'
        EYE_GAZE = 'EYE_GAZE_LIVENESS'
        MAGNIFEYE = 'MAGNIFEYE_LIVENESS'

    def __init__(self, host, session=None, timeout=10, retry=None, configs=None):
        self.host = host
        self.session = session or requests.Session()
        self.timeout = timeout
        self.response = {}
        self.retry = retry or DEFAULT_API_RETRY
        self.elapsed = None
        self.configs = configs
        self.customer_id = None
        self.active_vendor_result = None
        self.passive_vendor_result = None
        self._headers = {}

    @property
    def headers(self):
        if not self._headers:
            self._headers = {
                "Authorization": "Bearer {}".format(settings.DDIS_TOKEN),
                'Content-Type': 'application/json',
            }

        return self._headers

    def create_customer(self):
        result, elapsed = self.request(
            api=self.API.CREATE_CUSTOMER,
            method='POST',
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
        )
        return result, elapsed

    def delete_customer(self):
        result, elapsed = self.request(
            api=self.API.DELETE_CUSTOMER.format(self.customer_id),
            method='DELETE',
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
            success_statuses=[HTTP_200_OK, HTTP_204_NO_CONTENT],
            json_response=False,
        )
        return result, elapsed

    def create_customer_selfie(self, image: str = None, selfie_origin_link: str = None):
        if image:
            data = {'image': {'data': image}}
        elif selfie_origin_link:
            data = {'selfieOrigin': {'link': selfie_origin_link}}
        result, elapsed = self.request(
            api=self.API.CREATE_CUSTOMER_SELFIE.format(self.customer_id),
            method='PUT',
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
            data=data,
        )
        return result, elapsed

    def create_customer_liveness(self):
        result, elapsed = self.request(
            api=self.API.CREATE_CUSTOMER_LIVENESS.format(self.customer_id),
            method='PUT',
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
        )
        return result, elapsed

    def provide_customer_liveness_selfie(self, selfie_origin_link):
        data = {"assertion": "NONE", "selfieOrigin": {"link": selfie_origin_link}}
        result, elapsed = self.request(
            api=self.API.UPLOAD_IMAGE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
        )
        return result, elapsed

    def upload_smile_image(self, image: str):
        result, elapsed = self._upload_image(self.UploadImageAssertionType.SMILE, image)

        return result, elapsed

    def upload_passive_image(self, image):
        result, elapsed = self._upload_image(self.UploadImageAssertionType.PASSIVE, image)

        return result, elapsed

    def upload_neutral_image(self, image):
        result, elapsed = self._upload_image(self.UploadImageAssertionType.NEUTRAL, image)

        return result, elapsed

    def _upload_image(self, assertion_type, image):
        data = {"assertion": assertion_type, "image": {"data": image}}
        result, elapsed = self.request(
            api=self.API.UPLOAD_IMAGE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
        )
        return result, elapsed

    def upload_record(self, record):
        result, elapsed = self.request(
            api=self.API.UPLOAD_CUSTOMER_LIVENESS_RECORD.format(self.customer_id),
            method='POST',
            data=record,
            headers={
                "Authorization": "Bearer {}".format(settings.DDIS_TOKEN),
                'Content-Type': 'application/octet-stream',
            },
        )
        return result, elapsed

    def generate_challenge(self, active_type):
        data = None
        if active_type == ActiveLivenessMethod.EYE_GAZE.value:
            data = {'type': self.EvaluateType.EYE_GAZE}
        elif active_type == ActiveLivenessMethod.SMILE.value:
            data = {'type': self.EvaluateType.SMILE}
        result, elapsed = self.request(
            api=self.API.CREATE_CUSTOMER_LIVENESS_RECORD_CHALLENGE.format(self.customer_id),
            method='PUT',
            data=data,
        )
        return result, elapsed

    def evaluate_smile(self):
        result, elapsed = self._evaluate(self.EvaluateType.SMILE)
        self.capture_response(self.API.EVALUATE, evaluate_type=LivenessCheckType.ACTIVE)

        return result, elapsed

    def evaluate_eye_gaze(self):
        result, elapsed = self._evaluate(self.EvaluateType.EYE_GAZE)
        self.capture_response(self.API.EVALUATE, evaluate_type=LivenessCheckType.ACTIVE)

        return result, elapsed

    def evaluate_magnifeye(self):
        result, elapsed = self._evaluate(self.EvaluateType.MAGNIFEYE)
        self.capture_response(self.API.EVALUATE, evaluate_type=LivenessCheckType.ACTIVE)

        return result, elapsed

    def evaluate_passive(self):
        result, elapsed = self._evaluate(self.EvaluateType.PASSIVE)
        self.capture_response(self.API.EVALUATE, evaluate_type=LivenessCheckType.PASSIVE)

        return result, elapsed

    def _evaluate(self, evaluate_type):
        data = {"type": evaluate_type}
        result, elapsed = self.request(
            api=self.API.EVALUATE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.configs.get('timeout_retry'),
            timeout=self.configs.get('timeout'),
        )
        return result, elapsed

    def inspect_customer(self):
        result, elapsed = self.request(
            api=self.API.INSPECT_CUSTOMER.format(self.customer_id),
            method='POST',
        )
        return result, elapsed

    def get_api_info(self):
        cache_client = get_redis_cache()
        result = cache_client.get(CacheKeys.DDIS_API_INFO['key'], {})
        elapsed = 0
        if not result:
            result, elapsed = self.request(
                api=self.API.SERVER_INFO,
                data=None,
                method='GET',
                retry_count=self.configs.get('timeout_retry'),
                timeout=self.configs.get('timeout'),
            )
            cache_client.set(
                CacheKeys.DDIS_API_INFO['key'], result, CacheKeys.DDIS_API_INFO['timeout']
            )

        return result, elapsed

    def request(
        self,
        api,
        method,
        data=None,
        retry_count=None,
        timeout=None,
        success_statuses: list = None,
        json_response: bool = True,
        headers=None,
    ):
        headers = headers or self.headers
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
                            url, params=data, timeout=timeout, headers=headers
                        )
                    else:
                        response = self.session.get(url, timeout=timeout, headers=headers)
                elif method == 'POST':
                    if headers['Content-Type'] == 'application/octet-stream':
                        response = self.session.post(
                            url, data=data, timeout=self.timeout, headers=headers
                        )
                    else:
                        response = self.session.post(
                            url, json=data, timeout=self.timeout, headers=headers
                        )
                elif method == 'PUT':
                    response = self.session.put(
                        url, json=data, timeout=self.timeout, headers=headers
                    )
                elif method == 'DELETE':
                    response = self.session.delete(
                        url, json=data, timeout=self.timeout, headers=headers
                    )

                elapsed = int((time.time() - start_time) * 1000)

                try:
                    if json_response:
                        self.response = response.json()
                    else:
                        self.response = response
                    logger.info(
                        'DDIS_live_detection_response|url={}, method={}, response={}'.format(
                            url, method, self.response
                        )
                    )
                except ValueError as error:
                    raise DotClientInternalError(str(error))

                _success_statuses = success_statuses or [HTTP_200_OK]
                if response.status_code in _success_statuses:
                    return self.response, elapsed

                error_message = 'dot_client_request_failed|api={}, status={}, response={}'.format(
                    url, response.status_code, response.text
                )
                logger.warning(error_message)
                if (
                    HTTP_400_BAD_REQUEST
                    <= int(response.status_code)
                    < HTTP_500_INTERNAL_SERVER_ERROR
                ):
                    raise DotClientError(
                        {
                            'response': self.response,
                            'status': response.status_code,
                            'elapsed': elapsed,
                        }
                    )

                raise DotServerError(
                    {'response': self.response, 'status': response.status_code, 'elapsed': elapsed}
                )

            except (
                requests.exceptions.ConnectTimeout,
                requests.exceptions.Timeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as error:
                logger.exception(
                    "dot_client_request_timeout|api={}, error={}".format(api, str(error))
                )
                if retry_count <= 0:
                    raise DotServerTimeout(str(error))
            except (DotClientError, DotServerError) as error:
                raise error
            except Exception as error:
                logger.exception(
                    "dot_client_request_exception|api={}, error={}".format(api, str(error))
                )
                if retry_count <= 0:
                    raise DotClientInternalError(str(error))

    def capture_response(self, api: str, *args, **kwargs):
        if api == self.API.EVALUATE:
            if kwargs.get('evaluate_type') == LivenessCheckType.ACTIVE:
                self.active_vendor_result = ActiveLivenessVendorResult.objects.create(
                    vendor_name=LivenessVendor.INNOVATRICS,
                    raw_response=self.response,
                    raw_response_type=LivenessCheckType.ACTIVE,
                )
                return
            if kwargs.get('evaluate_type') == LivenessCheckType.PASSIVE:
                self.passive_vendor_result = PassiveLivenessVendorResult.objects.create(
                    vendor_name=LivenessVendor.INNOVATRICS,
                    raw_response=self.response,
                    raw_response_type=LivenessCheckType.PASSIVE,
                )
                return


def get_dot_digital_identity_client(configs: dict) -> DotDigitalIdentityClient:
    client = DotDigitalIdentityClient(settings.DOT_DIGITAL_IDENTITY_API_BASE_URL, configs=configs)

    return client
