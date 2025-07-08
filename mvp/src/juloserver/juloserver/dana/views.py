import time
import logging
from datetime import datetime
from typing import Any
from collections import OrderedDict
from itertools import chain

import pytz
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView

from juloserver.dana.constants import ErrorType, DanaBasePath, BindingRejectCode
from juloserver.dana.exceptions import (
    APIError,
    APIInvalidFieldFormatError,
    APIUnauthorizedError,
    APIMandatoryFieldError,
)
from juloserver.dana.security import DanaAuthentication
from juloserver.dana.utils import (
    get_error_message,
    all_equal,
    get_error_type,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

from typing import Dict


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class DanaAPIView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [DanaAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, APIUnauthorizedError):
            return Response(status=exc.status_code, data=exc.detail)

        if isinstance(exc, APIError):
            return Response(status=exc.status_code, data=exc.detail)

        if isinstance(exc, ValidationError):
            error_type = ErrorType.BAD_REQUEST
            error_details = []

            for error_detail in exc.detail.values():
                if isinstance(error_detail, list):
                    error_details.append(error_detail)
                elif isinstance(error_detail, OrderedDict):
                    error_details += list(error_detail.values())
            error_details = list(chain.from_iterable(error_details))
            is_all_error_equal = all_equal(error_details)
            if is_all_error_equal:
                error_type = get_error_type(error_details[0])
            response_code, response_message = get_error_message(self.base_path, error_type)

            if self.base_path == DanaBasePath.refund:
                refund_time = ''
                additionalInfo = exc.detail.serializer.initial_data.get('additionalInfo')
                if additionalInfo:
                    refund_time = additionalInfo.get('refundTime', '')

                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'originalPartnerReferenceNo': exc.detail.serializer.initial_data.get(
                        'originalPartnerReferenceNo', ''
                    ),
                    'originalExternalId': exc.detail.serializer.initial_data.get(
                        'originalExternalId', ''
                    ),
                    'refundNo': '',
                    'partnerRefundNo': exc.detail.serializer.initial_data.get(
                        'partnerRefundNo', ''
                    ),
                    'refundAmount': exc.detail.serializer.initial_data.get('refundAmount', ''),
                    'refundTime': refund_time,
                    'additionalInfo': {"errors": exc.detail},
                }
            else:
                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'partnerReferenceNo': exc.detail.serializer.initial_data.get(
                        'partnerReferenceNo'
                    ),
                    'additionalInfo': {"errors": exc.detail},
                }

            if self.base_path == DanaBasePath.onboarding:
                data['additionalInfo'][
                    'rejectCode'
                ] = BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.code
                data['additionalInfo'][
                    'rejectReason'
                ] = BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.reason

            if self.base_path == DanaBasePath.account:
                data['additionalInfo'][
                    'rejectCode'
                ] = BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.code
                data['additionalInfo'][
                    'rejectReason'
                ] = BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.reason

            return Response(status=exc.status_code, data=data)

        if isinstance(exc, APIInvalidFieldFormatError):
            response_code, response_message = get_error_message(
                self.base_path, ErrorType.INVALID_FIELD_FORMAT
            )

            try:
                partner_reference_no = self.request.data.get('partnerReferenceNo', '')
            except Exception:
                partner_reference_no = ''

            if self.base_path == DanaBasePath.refund:
                refund_time = ''
                additionalInfo = self.request.data.get('additionalInfo')
                if additionalInfo:
                    refund_time = additionalInfo.get('refundTime', '')

                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'originalPartnerReferenceNo': self.request.data.get(
                        'originalPartnerReferenceNo', ''
                    ),
                    'originalExternalId': self.request.data.get('originalExternalId', ''),
                    'refundNo': '',
                    'partnerRefundNo': self.request.data.get('partnerRefundNo', ''),
                    'refundAmount': self.request.data.get('refundAmount', ''),
                    'refundTime': refund_time,
                    'additionalInfo': {"errors": exc.detail},
                }
            else:
                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {"errors": exc.detail},
                }

            if self.base_path == DanaBasePath.onboarding:
                data['additionalInfo'][
                    'rejectCode'
                ] = BindingRejectCode.HAS_INVALID_FIELD_FORMAT.code
                data['additionalInfo'][
                    'rejectReason'
                ] = BindingRejectCode.HAS_INVALID_FIELD_FORMAT.reason

            return Response(status=exc.status_code, data=data)

        if isinstance(exc, APIMandatoryFieldError):
            response_code, response_message = get_error_message(
                self.base_path, ErrorType.INVALID_MANDATORY_FIELD
            )

            try:
                partner_reference_no = self.request.data.get('partnerReferenceNo', '')
            except Exception:
                partner_reference_no = ''

            if self.base_path == DanaBasePath.refund:
                refund_time = ''
                additionalInfo = self.request.data.get('additionalInfo')
                if additionalInfo:
                    refund_time = additionalInfo.get('refundTime', '')

                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'originalPartnerReferenceNo': self.request.data.get(
                        'originalPartnerReferenceNo', ''
                    ),
                    'originalExternalId': self.request.data.get('originalExternalId', ''),
                    'refundNo': '',
                    'partnerRefundNo': self.request.data.get('partnerRefundNo', ''),
                    'refundAmount': self.request.data.get('refundAmount', ''),
                    'refundTime': refund_time,
                    'additionalInfo': {"errors": exc.detail},
                }
            else:
                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {"errors": exc.detail},
                }

            return Response(status=exc.status_code, data=data)

        # Unhandled error 500 raise to sentry and standarized the error
        if isinstance(exc, Exception):
            if 'CreditScore matching query does not exist' not in str(exc):
                sentry_client.captureException()

            response_code, response_message = get_error_message(
                self.base_path, ErrorType.GENERAL_ERROR
            )

            try:
                partner_reference_no = self.request.data.get('partnerReferenceNo', '')
            except Exception:
                partner_reference_no = ''

            if self.base_path == DanaBasePath.refund:
                refund_time = ''
                additionalInfo = self.request.data.get('additionalInfo')
                if additionalInfo:
                    refund_time = additionalInfo.get('refundTime', '')

                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'originalPartnerReferenceNo': self.request.data.get(
                        'originalPartnerReferenceNo', ''
                    ),
                    'originalExternalId': self.request.data.get('originalExternalId', ''),
                    'refundNo': '',
                    'partnerRefundNo': self.request.data.get('partnerRefundNo', ''),
                    'refundAmount': self.request.data.get('refundAmount', ''),
                    'refundTime': refund_time,
                    'additionalInfo': {},
                }
            else:
                data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {},
                }

            if self.base_path == DanaBasePath.onboarding:
                data['additionalInfo']['rejectCode'] = BindingRejectCode.INTERNAL_SERVER_ERROR.code
                data['additionalInfo'][
                    'rejectReason'
                ] = BindingRejectCode.INTERNAL_SERVER_ERROR.reason

            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR, data=data)

        return super().handle_exception(exc)

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DANA_MASSIVE_LOG,
        ).first()

        log_execution_time = None
        if feature_setting and feature_setting.is_active:
            start_time = time.time()
            start_datetime = timezone.localtime(timezone.now())

        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)

        if feature_setting and feature_setting.is_active:
            end_time = time.time()
            end_datetime = timezone.localtime(timezone.now())

            exec_time = end_time - start_time
            if exec_time < 0:
                time_exec_format = "{} ms".format((exec_time * 1000))
            else:
                time_exec_format = "{} s".format(exec_time)

            log_execution_time = {
                'start_datetime': (
                    start_datetime.strftime("%Y-%m-%dT%H:%M:%S:%f") if start_datetime else None
                ),
                'end_datetime': (
                    end_datetime.strftime("%Y-%m-%dT%H:%M:%S:%f") if end_datetime else None
                ),
                'execution_time': time_exec_format,
            }

        self._log_request(raw_body, request, response, log_execution_time)
        tz = pytz.timezone("Asia/Jakarta")
        now = datetime.now(tz=tz)
        response["X-TIMESTAMP"] = "{}+07:00".format(now.strftime("%Y-%m-%dT%H:%M:%S"))

        return response

    def _log_request(
        self,
        request_body: bytes,
        request: Request,
        response: Response,
        log_execution_time: Dict = None,
    ) -> None:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        # Mapping a Headers
        headers = {
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_X_SIGNATURE': signature,
            'HTTP_X_PARTNER_ID': partner_id,
            'HTTP_X_EXTERNAL_ID': external_id,
            'HTTP_CHANNEL_ID': channel_id,
        }

        # Log every API Request and Response
        data = ''
        if hasattr(response, "data"):
            data = response.data
        elif hasattr(response, "url"):
            data = response.url

        data_to_log = {
            "action": "dana_api_view_logs",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.build_absolute_uri(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": data,
        }

        if log_execution_time:
            data_to_log['log_execution_time'] = log_execution_time

        logger.info(data_to_log)
