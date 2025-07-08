from juloserver.dana.constants import ErrorType, DanaBasePath
from juloserver.dana.exceptions import APIUnauthorizedError
from juloserver.dana.utils import create_string_to_sign, get_error_message, is_valid_signature

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from typing import Any

from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting


class DanaAuthentication(BaseAuthentication):
    """
    Content-Type: application/json
    X-TIMESTAMP: Transaction date time, in format YYYY-MM-DDTHH:mm:ss+07:00. (GMT+7)
    X-SIGNATURE: Siganture generated based on sha256 signature with private key
    X-PARTNER-ID: Unique identifier for partner known as Client ID (generated in julo)
    X-EXTERNAL-ID: Unique messaging reference identifier unique within the same day
    X-CHANNEL-ID: Device identification on the API services (customer)
    """

    def authenticate(self, request: Request) -> Any:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        # Handle different error code, between endpoints
        repayment_path = '/repayment-host-to-host'
        payment_path = '/payment-host-to-host'
        refund_path = 'refund'
        account_path = '/user/update/account-info'
        payment_query_path = '/status'
        account_inquiry_path = '/registration-account-inquiry'
        account_info_path = '/user/query/account-info'

        if payment_path in request.path:
            base_path = DanaBasePath.loan
        elif repayment_path in request.path:
            base_path = DanaBasePath.repayment
        elif refund_path in request.path:
            base_path = DanaBasePath.refund
        elif account_path in request.path:
            base_path = DanaBasePath.account
        elif payment_query_path in request.path:
            base_path = DanaBasePath.loan_status
        elif account_inquiry_path in request.path:
            base_path = DanaBasePath.account_inquiry
        elif account_info_path in request.path:
            base_path = DanaBasePath.account_info
        else:
            base_path = DanaBasePath.onboarding

        response_code, response_message = get_error_message(base_path, ErrorType.INVALID_SIGNATURE)

        body = ''
        partner_reference_no = ''
        if request.data:
            body = request.data
            partner_reference_no = body.get('partnerReferenceNo', '')

        error_message = {
            'responseCode': response_code,
            'responseMessage': response_message,
            'partnerReferenceNo': partner_reference_no,
            'additionalInfo': {},
        }
        if not timestamp or not signature or not partner_id or not external_id or not channel_id:
            raise APIUnauthorizedError(detail=error_message)

        is_use_ascii_only = False
        dana_auth_config = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DANA_AUTH_CONFIG, is_active=True
        ).first()
        if dana_auth_config and dana_auth_config.parameters:
            is_use_ascii_only = dana_auth_config.parameters.get('is_use_ascii_only', False)

        string_to_sign = create_string_to_sign(
            request.method, request.path, body, str(timestamp), is_use_ascii_only
        )

        if not is_valid_signature(signature, string_to_sign):
            raise APIUnauthorizedError(detail=error_message)
