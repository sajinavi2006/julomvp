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

from juloserver.liveness_detection.exceptions import (
    DotClientError,
    DotClientInternalError,
    DotServerError,
    DotServerTimeout,
)

logger = logging.getLogger(__name__)


class PartnershipDotDigitalIdentityClient:
    class API:
        CREATE_CUSTOMER = '/api/v1/customers'
        CREATE_CUSTOMER_SELFIE = '/api/v1/customers/{}/selfie'  # use the neutral image
        CREATE_CUSTOMER_LIVENESS = '/api/v1/customers/{}/liveness'
        UPLOAD_IMAGE = '/api/v1/customers/{}/liveness/selfies'  # assertion=SMILE
        EVALUATE = '/api/v1/customers/{}/liveness/evaluation'
        SERVER_INFO = '/api/v1/info'
        DELETE_CUSTOMER = '/api/v1/customers/{}'

    class UploadImageAssertionType:
        SMILE = 'SMILE'
        NEUTRAL = 'NEUTRAL'
        PASSIVE = 'NONE'

    class EvaluateType:
        SMILE = 'SMILE_LIVENESS'
        PASSIVE = 'PASSIVE_LIVENESS'

    def __init__(self, session=None, retry=None, configs=None):
        self.host = settings.DOT_DIGITAL_IDENTITY_API_BASE_URL
        self.session = requests.Session()
        self.timeout = 10
        self.response = {}
        self.retry = 3
        self.elapsed = None
        self.customer_id = None
        self.smile_vendor_result = None
        self.passive_vendor_result = None
        self.headers = {
            "Authorization": "Bearer {}".format(settings.DDIS_TOKEN),
            'Content-Type': 'application/json',
        }

    def request(
        self,
        api,
        method,
        data=None,
        retry_count=None,
        timeout=None,
    ):
        timeout = self.timeout
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
                            url, params=data, timeout=timeout, headers=self.headers
                        )
                    else:
                        response = self.session.get(url, timeout=timeout, headers=self.headers)
                elif method == 'POST':
                    response = self.session.post(
                        url, json=data, timeout=self.timeout, headers=self.headers
                    )
                elif method == 'PUT':
                    response = self.session.put(
                        url, json=data, timeout=self.timeout, headers=self.headers
                    )
                elif method == 'DELETE':
                    response = self.session.delete(
                        url, json=data, timeout=self.timeout, headers=self.headers
                    )

                # calculate the elapsed in milliseconds
                elapsed = int((time.time() - start_time) * 1000)

                try:
                    if response.status_code == HTTP_204_NO_CONTENT:
                        self.response = response
                    else:
                        self.response = response.json()
                    logger.info(
                        {
                            "action": "SuccessPartnershipDotDigitalIdentityClient",
                            "method": method,
                            "url": url,
                            "response": self.response,
                        }
                    )
                except ValueError as error:
                    raise DotClientInternalError(str(error))

                if response.status_code in {HTTP_200_OK, HTTP_204_NO_CONTENT}:
                    return self.response, elapsed

                logger.warning(
                    {
                        "action": "FailedPartnershipDotDigitalIdentityClient",
                        "method": method,
                        "url": url,
                        "status": response.status_code,
                        "response": response.text,
                    }
                )
                if (
                    HTTP_400_BAD_REQUEST
                    <= int(response.status_code)
                    < HTTP_500_INTERNAL_SERVER_ERROR
                ):
                    logger.warning(
                        {
                            "action": "FailedPartnershipDotDigitalIdentityClient",
                            "method": method,
                            "url": url,
                            "status": response.status_code,
                            "response": response.text,
                        }
                    )
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
                    {
                        "action": "FailedPartnershipDotDigitalIdentityClient",
                        "message": "dot_client_request_timeout",
                        "method": method,
                        "url": url,
                        "error": str(error),
                    }
                )
                if retry_count <= 0:
                    raise DotServerTimeout(str(error))
            except (DotClientError, DotServerError) as error:
                raise error
            except Exception as error:
                logger.exception(
                    {
                        "action": "FailedPartnershipDotDigitalIdentityClient",
                        "message": "dot_client_request_exception",
                        "method": method,
                        "url": url,
                        "error": str(error),
                    }
                )
                if retry_count <= 0:
                    raise DotClientInternalError(str(error))

    def create_customer_innovatrics(self):
        result, elapsed = self.request(
            api=self.API.CREATE_CUSTOMER,
            method='POST',
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed

    def delete_customer_innovatrics(self):
        try:
            result, elapsed = self.request(
                api=self.API.DELETE_CUSTOMER.format(self.customer_id),
                method='DELETE',
                retry_count=self.retry,
                timeout=self.timeout,
            )
            logger.info(
                {
                    'action': 'delete_customer_innovatrics',
                    'message': "success delete customer innovatrics",
                    'elapsed': "{} Millisecond".format(elapsed),
                }
            )
            return result, False
        except Exception as e:
            logger.exception(
                {
                    'action': 'failed_delete_customer_innovatrics',
                    'message': "failed delete customer innovatrics",
                    'error': str(e),
                }
            )
            return "failed delete_customer", True

    def create_customer_liveness(self):
        result, elapsed = self.request(
            api=self.API.CREATE_CUSTOMER_LIVENESS.format(self.customer_id),
            method='PUT',
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed

    def submit_smile_image(self, image: str):
        data = {"assertion": self.UploadImageAssertionType.SMILE, "image": {"data": image}}
        result, elapsed = self.request(
            api=self.API.UPLOAD_IMAGE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed

    def submit_neutral_image(self, image: str):
        data = {"assertion": self.UploadImageAssertionType.NEUTRAL, "image": {"data": image}}
        result, elapsed = self.request(
            api=self.API.UPLOAD_IMAGE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed

    def submit_passive_image(self, image: str):
        data = {"assertion": self.UploadImageAssertionType.PASSIVE, "image": {"data": image}}
        result, elapsed = self.request(
            api=self.API.UPLOAD_IMAGE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed

    def evaluate_passive(self):
        data = {"type": self.EvaluateType.PASSIVE}
        result, elapsed = self.request(
            api=self.API.EVALUATE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed

    def evaluate_smile(self):
        data = {"type": self.EvaluateType.SMILE}
        result, elapsed = self.request(
            api=self.API.EVALUATE.format(self.customer_id),
            method='POST',
            data=data,
            retry_count=self.retry,
            timeout=self.timeout,
        )
        return result, elapsed
