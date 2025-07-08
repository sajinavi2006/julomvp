from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request
from rest_framework.exceptions import APIException
from rest_framework.status import (
    HTTP_401_UNAUTHORIZED,
)

from typing import Any, Dict

from juloserver.integapiv1.constants import (
    FaspaySnapInquiryResponseCodeAndMessage,
    FaspaySnapPaymentResponseCodeAndMessage,
)
from juloserver.integapiv1.services import faspay_generate_string_to_sign
from juloserver.integapiv1.utils import verify_asymmetric_signature


class APIUnauthorizedError(APIException):
    def __init__(self, detail: Dict = {}) -> None:
        self.status_code = HTTP_401_UNAUTHORIZED
        self.detail = detail


class FaspaySnapAuthentication(BaseAuthentication):
    """
    Content-Type: application/json
    X-TIMESTAMP: Client's current local time in yyyy-MM-ddTHH:mm:ssTZD format
    X-SIGNATURE: Siganture generated based on sha256 signature with private key
    X-PARTNER-ID: Unique ID for a partner. merchant_id.
    X-EXTERNAL-ID: Numeric String. Reference number that should be unique in the same day
    X-CHANNEL-ID: Channel identifier using Faspay’s API Service (77001)
    """

    def authenticate(self, request: Request) -> Any:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        if 'inquiry' in request.path:
            error_message = {
                'responseCode': FaspaySnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                'responseMessage': FaspaySnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message,
            }
        elif 'payment' in request.path:
            error_message = {
                'responseCode': FaspaySnapPaymentResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                'responseMessage': FaspaySnapPaymentResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message,
            }
        else:
            error_message = {
                'responseCode': FaspaySnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                'responseMessage': FaspaySnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message,
            }

        if not timestamp or not signature or not partner_id or not external_id or not channel_id:
            raise APIUnauthorizedError(detail=error_message)

        data = request.data
        relative_url = request.get_full_path()[request.get_full_path().find('/v1.0') :]
        string_to_sign = faspay_generate_string_to_sign(
            data, request.method, relative_url, timestamp
        )
        public_key = settings.FASPAY_SNAP_PUBLIC_KEY
        is_valid_signature = verify_asymmetric_signature(public_key, signature, string_to_sign)

        if not is_valid_signature:
            raise APIUnauthorizedError(detail=error_message)
