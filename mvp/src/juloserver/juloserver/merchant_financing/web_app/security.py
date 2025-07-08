from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from typing import Any

from juloserver.merchant_financing.web_app.utils import (
    decode_jwt_token,
    verify_token_is_active,
    verify_access_token,
    get_user_from_token,
)
from juloserver.merchant_financing.web_app.constants import WebAppErrorMessage
from juloserver.partnership.constants import PartnershipTokenType, PartnershipProductCategory
from juloserver.partnership.exceptions import APIUnauthorizedError
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.models import PartnershipJSONWebToken


class WebAppAuthentication(BaseAuthentication):

    def authenticate(self, request: Request) -> Any:
        access_token = verify_access_token(request.META.get('HTTP_AUTHORIZATION'))

        if not access_token:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_AUTH)

        verify_token = decode_jwt_token(access_token)
        # to check the still valid or not
        if not verify_token:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_TOKEN)

        is_active_token = verify_token_is_active(
            access_token,
            PartnershipTokenType.ACCESS_TOKEN
        )

        # to check this token is active or not
        if not is_active_token:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_TOKEN)

        # Set user data from access_token
        request.user_obj = get_user_from_token(access_token)


class MFStandardAPIAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> Any:
        auth_token = request.META.get('HTTP_AUTHORIZATION')

        if not auth_token:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_AUTH)

        bearer_token = auth_token.split()
        if len(bearer_token) != 2 or bearer_token[0].lower() != 'bearer':
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_TOKEN)

        jwt_token = JWTManager(product_category=PartnershipProductCategory.MERCHANT_FINANCING)
        decoded_token = jwt_token.decode_token(bearer_token[1])

        if not decoded_token:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_TOKEN)

        token_type = decoded_token.get('type')
        partner_name = decoded_token.get('partner')

        is_invalid_request = (
            not partner_name or token_type.lower() != PartnershipTokenType.ACCESS_TOKEN.lower()
        )

        if is_invalid_request:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_TOKEN)

        active_token = PartnershipJSONWebToken.objects.filter(
            token=bearer_token[1],
            is_active=True,
            partner_name=partner_name.lower(),
            token_type=token_type,
        ).last()

        if not active_token:
            raise APIUnauthorizedError(WebAppErrorMessage.INVALID_TOKEN)

        request.user_obj = active_token.user
        request.partner_name = partner_name.lower()
