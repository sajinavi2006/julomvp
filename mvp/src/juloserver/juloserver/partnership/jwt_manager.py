import jwt
import logging

from datetime import datetime
from django_bulk_update.helper import bulk_update
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from hashids import Hashids

from juloserver.partnership.constants import (
    HashidsConstant,
    JWTLifetime,
    PartnershipTokenType,
    PartnershipProductCategory,
)
from juloserver.julo.models import Application
from juloserver.partnership.models import PartnershipJSONWebToken

from typing import Dict, Union

logger = logging.getLogger(__name__)


class JWTManagerException(Exception):
    pass


class JWTManager:
    def __init__(
        self,
        user: User = None,
        partner_name: str = None,
        application_xid: str = None,
        product_category: str = None,  # for set secret key and salt
        product_id: int = None,
        is_anonymous: bool = False,
    ):
        self.secret_key = settings.PARTNERSHIP_JWT_SECRET_KEY
        self.salt = settings.PARTNERSHIP_HASH_ID_SALT
        if product_category and product_category == PartnershipProductCategory.MERCHANT_FINANCING:
            self.secret_key = settings.MERCHANT_FINANCING_JWT_SECRET_KEY
            self.salt = settings.MERCHANT_FINANCING_HASH_ID_SALT
        self.user = user
        self.partner_name = partner_name
        self.application_xid = application_xid
        self.algorithm = 'HS256'
        self.product_id = product_id
        self.is_anonymous = is_anonymous

    def encode_token(self, payload: Dict) -> str:
        encoded_payload = jwt.encode(
            payload, self.secret_key, self.algorithm
        )

        return encoded_payload

    def decode_token(self, token: str) -> Union[bool, Dict]:
        try:
            decoded_token = jwt.decode(token, self.secret_key, self.algorithm)
        except jwt.ExpiredSignatureError:
            logger.info(
                {
                    'action': 'partnership_decode_token',
                    'message': 'Token expired',
                }
            )
            return False
        except Exception:
            logger.info(
                {
                    'action': 'partnership_decode_token',
                    'message': 'Failed to decode JWT exception',
                }
            )
            return False

        return decoded_token

    def create_or_update_token(self, token_type: str) -> PartnershipJSONWebToken:
        if not self.user:
            raise JWTManagerException('User must be provided')

        if not self.partner_name:
            raise JWTManagerException("Partner name must be provided")

        hashids = Hashids(min_length=HashidsConstant.MIN_LENGTH, salt=self.salt)

        is_lifetime = False
        if token_type == PartnershipTokenType.ACCESS_TOKEN:
            expired_token = JWTLifetime.ACCESS.value
        elif token_type == PartnershipTokenType.REFRESH_TOKEN:
            expired_token = JWTLifetime.REFRESH.value
        elif token_type == PartnershipTokenType.LIFETIME:
            expired_token = JWTLifetime.ACCESS.value
            is_lifetime = True
        elif token_type == PartnershipTokenType.OTP_LOGIN_VERIFICATION:
            expired_token = JWTLifetime.ACCESS.value
        elif token_type == PartnershipTokenType.RESET_PIN_TOKEN:
            expired_token = JWTLifetime.RESET_PIN.value
        elif token_type == PartnershipTokenType.CHANGE_PIN:
            expired_token = JWTLifetime.RESET_PIN.value
        else:
            raise JWTManagerException(
                "Invalid token type, must be access_token or refresh_token"
            )

        if is_lifetime:
            payload = {
                'partner': self.partner_name.lower(),
                'type': token_type,
                'iat': datetime.now(timezone.utc),
                'user': hashids.encode(self.user.id),
                'product_id': self.product_id,
                'is_anonymous': self.is_anonymous,
                'sub': str(0),
                'ctid': 0,
                'atid': 0,
            }
        else:
            payload = {
                'partner': self.partner_name.lower(),
                'type': token_type,
                'exp': datetime.now(timezone.utc) + expired_token,
                'iat': datetime.now(timezone.utc),
                'user': hashids.encode(self.user.id),
                'product_id': self.product_id,
                'is_anonymous': self.is_anonymous,
                'sub': str(0),
                'ctid': 0,
                'atid': 0,
            }

            if self.application_xid:
                payload['sub'] = str(self.application_xid)
                application = (
                    Application.objects.filter(application_xid=self.application_xid)
                    .values("id", "customer_id")
                    .last()
                )
                if application:
                    payload['ctid'] = application.get('customer_id')  # Customer ID
                    payload['atid'] = application.get('id')  # Appplication ID

        user_token = PartnershipJSONWebToken.objects.filter(
            user=self.user,
            partner_name=self.partner_name,
            token_type=token_type,
        ).last()

        raw_token = self.encode_token(payload)
        new_token = raw_token.decode('utf-8')

        if not user_token:
            expired_at = datetime.fromtimestamp(payload.get('exp')) if payload.get('exp') else None

            user_token = PartnershipJSONWebToken.objects.create(
                user=self.user,
                expired_at=expired_at,
                name=self.user.first_name,
                partner_name=self.partner_name,
                token_type=token_type,
                token=new_token,
                is_active=True,
            )

        else:
            expired_at = datetime.fromtimestamp(payload.get('exp')) if payload.get('exp') else None
            is_not_expired_token = self.decode_token(user_token.token)
            is_active_token = user_token.is_active

            if is_not_expired_token and is_active_token:
                return user_token

            user_token.token = new_token
            user_token.is_active = True
            user_token.expired_at = expired_at
            user_token.save(update_fields=['token', 'expired_at', 'is_active'])
            user_token.refresh_from_db()

        return user_token

    def inactivate_token(self, token: str) -> None:
        decoded_token = self.decode_token(token)
        hashids = Hashids(min_length=HashidsConstant.MIN_LENGTH, salt=self.salt)
        user = hashids.decode(decoded_token['user'])[0]
        partner_name = decoded_token.get('partner')
        user_tokens = PartnershipJSONWebToken.objects.filter(
            user_id=user,
            partner_name=partner_name,
            is_active=True,
        )
        token_list = []
        for user_token in user_tokens:
            user_token.udate = timezone.localtime(timezone.now())
            user_token.is_active = False
            token_list.append(user_token)
        bulk_update(token_list, update_fields=['is_active', 'udate'])

    def deactivate_token(self, token: str) -> None:
        """
        TODO: This code need to remove later, because this degrade the performance
        """
        user_token = PartnershipJSONWebToken.objects.filter(
            token=token,
        ).last()

        if user_token:
            user_token.update_safely(is_active=False)
        else:
            logger.info(
                {
                    "action": "partnership_deactivate_jwt_token",
                    "message": "user token not found",
                    "token": token,
                }
            )

    def activate_token(self, token: str) -> None:
        """
        TODO: This code need to remove later, because this degrade the performance
        """
        user_token = PartnershipJSONWebToken.objects.filter(
            token=token,
        ).last()

        if user_token:
            user_token.update_safely(is_active=True)
        else:
            logger.info(
                {
                    "action": "partnership_activate_jwt_token",
                    "message": "user token not found",
                    "token": token,
                }
            )
