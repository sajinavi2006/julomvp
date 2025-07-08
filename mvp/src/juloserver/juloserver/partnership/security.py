import re
from django.conf import settings
from rest_framework.request import Request
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from cuser.middleware import CuserMiddleware
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from juloserver.julo.partners import PartnerConstant
from juloserver.partnership.utils import get_aes_cypher
from juloserver.julo.services2.encryption import Encryption
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.julo.models import Partner
from juloserver.api_token.models import ExpiryToken
from juloserver.partnership.constants import (ErrorMessageConst,
                                              WHITELABEL_PAYLATER_REGEX,
                                              PAYLATER_REGEX,
                                              PartnershipTokenType, HTTPGeneralErrorMessage)
from juloserver.partnership.models import PartnershipCustomerData, PartnershipJSONWebToken

from juloserver.api_token.authentication import get_expiry_token
from juloserver.api_token.authentication import get_token_version_header, is_expired_token
from juloserver.partnership.exceptions import APIUnauthorizedError
from juloserver.partnership.jwt_manager import JWTManager

from typing import Any


def get_token_and_username(request):
    token_encrypted = request.META.get('HTTP_SECRET_KEY', b'')
    username = request.META.get('HTTP_USERNAME', b'')
    encrypt = Encryption()
    token_decrypted = encrypt.decode_string(token_encrypted)

    return token_decrypted, username


def get_decrypted_data_whitelabel(request):
    try:
        token_encrypted = request.META.get('HTTP_SECRET_KEY', b'')
        aes_cypher = get_aes_cypher()
        token_decrypted = aes_cypher.decrypt(token_encrypted)
    except Exception:
        raise exceptions.AuthenticationFailed('Invalid Key Error')
    return token_decrypted


class PartnershipAuthentication(ExpiryTokenAuthentication):

    def authenticate(self, request):
        token, username = get_token_and_username(request)
        user, token = self.authenticate_credentials(token)
        self.check_partner(user, username)

        return user, token

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = get_expiry_token(key, model)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_CREDENTIALS)

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.NOT_ACTIVE_USER)

        return (token.user, token)

    def check_partner(self, user, partner_username):
        if not hasattr(user, 'partner'):
            raise exceptions.AuthenticationFailed(ErrorMessageConst.NOT_PARTNER)
        elif not user.partner.is_active:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.NOT_PARTNER)
        elif str(user.username) != str(partner_username):
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_PARTNER)
        elif user.partner.is_grab:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_PARTNER)


class WhitelabelAuthentication(ExpiryTokenAuthentication):

    def authenticate(self, request):
        decrypted_data = get_decrypted_data_whitelabel(request)
        email, phone_number, partner, user, partner_reference_id, \
            paylater_transaction_xid, token_expiry_time, partner_customer_data, \
            email_phone_diff, \
            partner_origin_name = self.check_data_from_decrypted_data(decrypted_data)
        token = self.get_user_token_from_user(user)
        if not token:
            raise exceptions.AuthenticationFailed('Invalid Token')
        return user, token

    def check_data_from_decrypted_data(self, decrypted_data):
        regex = WHITELABEL_PAYLATER_REGEX
        regex1 = PAYLATER_REGEX
        try:
            if not (re.fullmatch(regex, decrypted_data)) and \
                    not (re.fullmatch(regex1, decrypted_data)):
                raise exceptions.AuthenticationFailed('Forbidden request, invalid Key')
            email, phone_number, partner_name, partner_reference_id, \
                public_key, paylater_transaction_xid, \
                token_expiry_time, partner_customer_data, email_phone_diff, \
                partner_origin_name = re.split(r':', decrypted_data)
        except Exception:
            raise exceptions.AuthenticationFailed('Invalid Request.')
        partner = Partner.objects.filter(
            name=partner_name,
            is_active=True
        ).select_related('user').last()
        if not partner:
            raise exceptions.AuthenticationFailed('Invalid Partner.')
        user = partner.user
        if public_key != settings.WHITELABEL_PUBLIC_KEY:
            raise exceptions.AuthenticationFailed('Forbidden request, invalid Key')

        return email, phone_number, partner, user, partner_reference_id, \
            paylater_transaction_xid, token_expiry_time, partner_customer_data, \
            email_phone_diff, partner_origin_name

    def get_user_token_from_user(self, user):
        expiry_token = ExpiryToken.objects.get(user=user)
        if expiry_token.is_active or expiry_token.is_never_expire:
            key = expiry_token.key
            return key


class IpriceAuthentication(PartnershipAuthentication):
    def check_partner(self, user, partner_username):
        super().check_partner(user, partner_username)
        if partner_username != PartnerConstant.IPRICE:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_PARTNER)


class JuloShopAuthentication(PartnershipAuthentication):
    def check_partner(self, user, partner_username):
        super().check_partner(user, partner_username)
        if partner_username != PartnerConstant.JULOSHOP:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_PARTNER)


class WebviewAuthentication(ExpiryTokenAuthentication):
    def authenticate(self, request):
        token, username = get_token_and_username_webview(request)
        user, token = self.authenticate_credential(
            token, username)
        return user, token

    def authenticate_credential(self, key, partner_name):
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            token=key,
            partner__name=partner_name
        )
        if not partnership_customer_data.filter(
            otp_status=PartnershipCustomerData.VERIFIED
        ).exists():
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_CREDENTIALS)
        partner = Partner.objects.filter(
            name=partner_name,
            is_active=True
        ).last()
        user = partner.user
        return user, key


def get_token_and_username_webview(request):
    token = request.META.get('HTTP_SECRET_KEY', b'')
    username = request.META.get('HTTP_USERNAME', b'')
    return token, username


class WebviewExpiryAuthentication(ExpiryTokenAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return result

        user, expiry_token = result

        if not expiry_token.is_never_expire and not expiry_token.is_active:
            if get_token_version_header(request):
                expiry_token.is_active = True
                expiry_token.generated_time = timezone.localtime(timezone.now())
                expiry_token.save()

        is_expired, _expire_on = is_expired_token(expiry_token)
        if is_expired:
            raise exceptions.AuthenticationFailed('Token Expired')

        CuserMiddleware.set_user(user)
        token, _ = get_token_and_username_webview(request)
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
        user, token = self.authenticate_credential(token, user, expiry_token,
                                                   paylater_transaction_xid)
        return user, expiry_token

    def authenticate_credential(self, key, user, expiry_token,
                                paylater_transaction_xid):
        model = self.get_model()
        try:
            token = get_expiry_token(expiry_token.key, model)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed(_('Invalid token.'))

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(_('User inactive or deleted.'))
        if (
                not paylater_transaction_xid or not str(paylater_transaction_xid).isdigit()
        ) and (
                not PartnershipCustomerData.objects.filter(
                    token=key, customer__user=user, otp_status=PartnershipCustomerData.VERIFIED
                ).exists()
        ):
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_CREDENTIALS)

        return token.user, token


class PartnershipJWTAuthentication(BaseAuthentication):

    def authenticate(self, request) -> Any:
        token = request.META.get('HTTP_AUTHORIZATION')

        if not token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(token)

        if not decoded_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        token_type = decoded_token.get('type')
        application_xid = decoded_token.get('sub')
        partner_name = decoded_token.get('partner')

        is_invalid_request = (
            (not token_type or not application_xid or not partner_name) or not request.partner_name
            or request.partner_name.lower() != partner_name.lower()
            or token_type.lower() != PartnershipTokenType.ACCESS_TOKEN.lower()
        )
        if is_invalid_request:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        active_token = PartnershipJSONWebToken.objects.filter(
            token=token, is_active=True,
            partner_name=partner_name.lower(),
            token_type=token_type
        ).last()

        if not active_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        request.user_obj = active_token.user
        request.user_token = token


class PartnershipMiniformJWTAuthentication(BaseAuthentication):

    def authenticate(self, request: Request) -> Any:
        token_header = request.META.get('HTTP_AUTHORIZATION')
        token = token_header[len('Bearer '):]

        if not token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(token)

        if not decoded_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        token_type = decoded_token.get('type')
        partner_name = decoded_token.get('partner')

        is_invalid_request = (
            (not token_type or not partner_name)
            or token_type.lower() != PartnershipTokenType.LIFETIME.lower()
        )
        if is_invalid_request:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        active_token = PartnershipJSONWebToken.objects.filter(
            token=token, is_active=True,
            partner_name=partner_name.lower(),
            token_type=token_type
        ).last()

        if not active_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        request.user_obj = active_token.user
        request.partner_name = partner_name.lower()


class AgentAssistedJWTAuthentication(BaseAuthentication):
    def authenticate(self, request) -> Any:
        token = request.META.get('HTTP_AUTHORIZATION')
        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(token)

        if not decoded_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        token_type = decoded_token.get('type')
        application_xid = decoded_token.get('sub')
        partner_name = decoded_token.get('partner')

        is_invalid_request = (
            (not token_type or not application_xid or not partner_name)
            or token_type.lower() != PartnershipTokenType.ACCESS_TOKEN.lower()
        )
        if is_invalid_request:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        active_token = PartnershipJSONWebToken.objects.filter(
            token=token, is_active=True, partner_name=partner_name.lower(), token_type=token_type
        ).last()

        if not active_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        request.user_obj = active_token.user
        request.user_token = token


class AegisServiceAuthentication(BaseAuthentication):
    def authenticate(self, request) -> Any:
        auth_token = request.META.get('HTTP_AUTHORIZATION')

        if not auth_token:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

        if auth_token != settings.AEGIS_SERVICE_TOKEN:
            raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)
