import jwt
from hashids import Hashids

from django.conf import settings
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from juloserver.partnership.constants import (
    PartnershipTokenType,
    HTTPGeneralErrorMessage,
    HashidsConstant,
)
from juloserver.partnership.leadgenb2b.onboarding.services import validate_allowed_partner
from juloserver.partnership.leadgenb2b.utils import get_active_token_data
from juloserver.partnership.models import PartnershipJSONWebToken
from juloserver.partnership.exceptions import APIUnauthorizedError, APIError
from juloserver.partnership.jwt_manager import JWTManager

from typing import Any, Union


class LeadgenAPIAuthentication(BaseAuthentication):
    def verify_token(self, authorization: str) -> Union[bool, str]:
        if not authorization:
            return False

        bearer_token = authorization.split(' ')
        if len(bearer_token) == 2 and bearer_token[0].lower() == 'bearer':
            return bearer_token[1]

        return False

    def authenticate(self, request) -> Any:
        token = self.verify_token(request.META.get('HTTP_AUTHORIZATION'))

        if not token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(token)

        if not decoded_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        token_type = decoded_token.get('type', '')
        user_id = decoded_token.get('user', '')
        partner_name = decoded_token.get('partner', '')
        is_anonymous = decoded_token.get('is_anonymous', False)

        if is_anonymous:
            APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        is_invalid_request = (
            token_type != PartnershipTokenType.ACCESS_TOKEN.lower()
            or not user_id
            or not partner_name
        )

        if is_invalid_request:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        hashids = Hashids(
            min_length=HashidsConstant.MIN_LENGTH, salt=settings.PARTNERSHIP_HASH_ID_SALT
        )

        user_id = hashids.decode(user_id)
        if not user_id:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        user_id = user_id[0]

        active_token = PartnershipJSONWebToken.objects.filter(
            user_id=user_id,
            is_active=True,
            partner_name=partner_name.lower(),
            token_type=token_type,
        ).last()

        if not active_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        if active_token.token != token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        request.user_obj = active_token.user
        request.user_token = token
        request.partner_name = partner_name
        return active_token.user, token


class LeadgenLoginOtpAPIAuthentication(BaseAuthentication):
    def verify_token(self, authorization: str) -> Union[bool, str]:
        if not authorization:
            return False

        bearer_token = authorization.split(' ')
        if len(bearer_token) == 2 and bearer_token[0].lower() == 'bearer':
            return bearer_token[1]

        return False

    def authenticate(self, request) -> Any:
        token = self.verify_token(request.META.get('HTTP_AUTHORIZATION'))

        if not token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(token)

        if not decoded_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        token_type = decoded_token.get('type', '')
        user_id = decoded_token.get('user', '')
        partner_name = decoded_token.get('partner', '')

        is_invalid_request = (
            token_type != PartnershipTokenType.OTP_LOGIN_VERIFICATION.lower()
            or not user_id
            or not partner_name
        )

        if is_invalid_request:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        hashids = Hashids(
            min_length=HashidsConstant.MIN_LENGTH, salt=settings.PARTNERSHIP_HASH_ID_SALT
        )

        user_id = hashids.decode(user_id)
        if not user_id:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        user_id = user_id[0]

        active_token = PartnershipJSONWebToken.objects.filter(
            user_id=user_id,
            is_active=True,
            partner_name=partner_name.lower(),
            token_type=token_type,
        ).last()

        if not active_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        if active_token.token != token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        request.user_obj = active_token.user
        request.user_token = token
        request.partner_name = partner_name
        return active_token.user, token


class LeadgenResetPinAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> Any:
        access_token = request.query_params.get("token")
        if not access_token:
            raise APIError(status_code=status.HTTP_404_NOT_FOUND)

        manager = JWTManager()

        try:
            decoded_token = jwt.decode(access_token, manager.secret_key, manager.algorithm)
        except jwt.ExpiredSignatureError:
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    'message': HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                    'meta': {'hasNewToken': False},
                },
            )
        except Exception:
            raise APIError(status_code=status.HTTP_404_NOT_FOUND)

        token_type = decoded_token.get("type", "")
        user_id = decoded_token.get("user", "")
        partner_name = decoded_token.get("partner", "")

        is_invalid_request = (
            token_type != PartnershipTokenType.RESET_PIN_TOKEN.lower()
            or not user_id
            or not partner_name
        )

        if is_invalid_request:
            raise APIError(status_code=status.HTTP_404_NOT_FOUND)

        hashids = Hashids(
            min_length=HashidsConstant.MIN_LENGTH, salt=settings.PARTNERSHIP_HASH_ID_SALT
        )

        user_id = hashids.decode(user_id)[0]
        active_token = PartnershipJSONWebToken.objects.filter(
            user_id=user_id,
            is_active=True,
            partner_name=partner_name.lower(),
            token_type=token_type,
        ).last()

        if not active_token:
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    'message': HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                    'meta': {'hasNewToken': False},
                },
            )

        if active_token.token != access_token:
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    'message': HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                    'meta': {'hasNewToken': False},
                },
            )

        validated = validate_allowed_partner(active_token.partner_name)
        if not validated:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        request.user_obj = active_token.user
        request.partner_name = active_token.partner_name


class LeadgenChangePinSubmissionAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> Any:
        access_token = request.query_params.get("token")

        if not access_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        active_token = get_active_token_data(access_token)

        validated = validate_allowed_partner(active_token.partner_name)
        if not validated:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        request.user_obj = active_token.user
        request.partner_name = active_token.partner_name
